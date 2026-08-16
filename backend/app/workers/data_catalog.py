"""Asynchronous layered data ingestion and safe feature materialization."""

import hashlib,io,json
from datetime import UTC,datetime,timedelta
from uuid import UUID
import numpy as np
import pandas as pd
from sqlalchemy import select
from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.object_storage import download_bytes,upload_bytes
from backend.app.models.data_catalog import DataSource,DataVersion,FactorResearchRun,FeatureDefinition,FeatureSnapshot
from backend.app.models.job import Job
from backend.app.services.factors import compute_factor
from backend.app.services.research_gates import factor_training_dates
from backend.app.services.universe import apply_dynamic_universe
from quant_core.validation import benjamini_hochberg, mean_significance
from quant_core import fetch_stock_data,fetch_akshare_stock_data,generate_demo_stock_data,validate_market_dataset

def _progress(jid,value):
    with SyncSessionFactory() as s:
        job=s.get(Job,jid)
        if job and job.status=="cancel_requested":job.status="canceled";job.completed_at=datetime.now(UTC);s.commit();raise RuntimeError("Task canceled")
        if job:
            job.progress=value
            job.lease_expires_at=datetime.now(UTC)+timedelta(hours=1)
            s.commit()
def _parquet(frame):
    out=io.BytesIO();frame.to_parquet(out,index=False);return out.getvalue()


def _fail(jid,message,records=()):
    with SyncSessionFactory() as s:
        job=s.get(Job,jid)
        if job:job.status="failed";job.error_message=message[:2000];job.completed_at=datetime.now(UTC);job.lease_expires_at=None
        for cls,rid in records:
            item=s.get(cls,rid)
            if item:item.status="failed";item.error_message=message[:2000]
        s.commit()

def sync_data(job_id:str):
    jid=UUID(job_id)
    with SyncSessionFactory() as s:
        job=s.get(Job,jid);payload=dict(job.payload);raw=s.get(DataVersion,UUID(payload["raw_version_id"]));standard=s.get(DataVersion,UUID(payload["standard_version_id"]));source=s.get(DataSource,raw.source_id)
        job.status="running";job.started_at=datetime.now(UTC);job.attempt+=1;job.lease_expires_at=datetime.now(UTC)+timedelta(minutes=15);raw.status=standard.status="running";s.commit()
    try:
        frames={}
        start,end=pd.Timestamp(payload["start_date"]).date(),pd.Timestamp(payload["end_date"]).date()
        for i,symbol in enumerate(payload["symbols"]):
            if source.provider=="demo":
                frames[symbol]=generate_demo_stock_data(start,end,seed=42+i)
            elif source.provider=="akshare":
                frames[symbol]=fetch_akshare_stock_data(
                    symbol,start.strftime("%Y%m%d"),end.strftime("%Y%m%d"),
                    adjust=str(source.configuration.get("adjust","qfq")),
                )
            else:
                frames[symbol]=fetch_stock_data(symbol,start.strftime("%Y%m%d"),end.strftime("%Y%m%d"))
            if (i + 1) % 5 == 0 or i + 1 == len(payload["symbols"]):
                _progress(jid,5+int(35*(i+1)/len(payload["symbols"])))
        raw_frame=pd.concat([f.assign(symbol=s,date=f.index) for s,f in frames.items()],ignore_index=True)
        raw_bytes=_parquet(raw_frame);raw_hash=hashlib.sha256(raw_bytes).hexdigest();raw_uri=upload_bytes(f"data/raw/{raw.id}/{raw_hash[:12]}.parquet",raw_bytes,"application/vnd.apache.parquet")
        _progress(jid,45)
        canonical,report=validate_market_dataset(frames)
        standard_frame=pd.concat([f.reset_index() for f in canonical.values()],ignore_index=True).sort_values(["date","symbol"])
        standard_frame,universe_report=apply_dynamic_universe(standard_frame,payload.get("universe_policy"))
        standard_bytes=_parquet(standard_frame);standard_hash=hashlib.sha256(standard_bytes).hexdigest();standard_uri=upload_bytes(f"data/standardized/{standard.id}/{standard_hash[:12]}.parquet",standard_bytes,"application/vnd.apache.parquet")
        with SyncSessionFactory() as s:
            job=s.get(Job,jid);r=s.get(DataVersion,raw.id);v=s.get(DataVersion,standard.id)
            r.status="ready";r.artifact_uri=raw_uri;r.content_sha256=raw_hash;r.row_count=len(raw_frame);r.quality_report={"raw_preserved":True};r.lineage={"provider":source.provider,"source_slug":source.slug,"ingested_at":datetime.now(UTC).isoformat()}
            quality={**report.to_dict(),"dynamic_universe":universe_report}
            v.status="ready";v.artifact_uri=standard_uri;v.content_sha256=standard_hash;v.row_count=len(standard_frame);v.quality_report=quality;v.lineage={"parent_id":str(r.id),"parent_sha256":raw_hash,"transform":"canonical_market_v2","dynamic_universe":universe_report}
            job.status="succeeded";job.progress=100;job.result_summary={"raw_version_id":str(r.id),"standard_version_id":str(v.id),"rows":len(standard_frame),"content_sha256":standard_hash};job.completed_at=datetime.now(UTC);job.lease_expires_at=None;s.commit()
        return job.result_summary
    except Exception as exc:_fail(jid,str(exc),[(DataVersion,raw.id),(DataVersion,standard.id)]);raise

def _compute(group,definition):
    return compute_factor(group,definition.implementation,definition.parameters)


def _compute_feature_column_with_diagnostics(frame, definition):
    """Return one factor column while preserving the original row order.

    ``DataFrameGroupBy.apply`` changes its shape when every group returns a
    similarly indexed Series: recent pandas versions may combine those Series
    into a DataFrame (one column per group).  A factor is always a single
    value per market row, so concatenate the per-symbol Series explicitly and
    align it back to the input index instead.
    """

    values = [_compute(group, definition) for _, group in frame.groupby("symbol", sort=False)]
    if not values:
        return pd.Series(index=frame.index, dtype=float), 0
    column = pd.concat(values)
    if not isinstance(column, pd.Series):
        raise ValueError(f"Factor {definition.slug} did not produce a single column")
    column = column.reindex(frame.index)
    numeric = pd.to_numeric(column, errors="coerce")
    non_finite_count = int(np.isinf(numeric).sum())
    return column.replace([np.inf, -np.inf], np.nan), non_finite_count


def _compute_feature_column(frame, definition):
    """Compute one JSON/Parquet-safe factor column for compatibility callers."""

    return _compute_feature_column_with_diagnostics(frame, definition)[0]

def materialize_features(job_id:str):
    jid=UUID(job_id)
    with SyncSessionFactory() as s:
        job=s.get(Job,jid);snap=s.get(FeatureSnapshot,UUID(job.payload["snapshot_id"]));version=s.get(DataVersion,snap.data_version_id)
        definitions=list(s.scalars(select(FeatureDefinition).where(FeatureDefinition.id.in_([UUID(x) for x in snap.feature_definition_ids]))).all())
        job.status="running";job.started_at=datetime.now(UTC);job.attempt+=1;job.lease_expires_at=datetime.now(UTC)+timedelta(hours=1);snap.status="running";s.commit()
    try:
        frame=pd.read_parquet(io.BytesIO(download_bytes(version.artifact_uri))).sort_values(["symbol","date"])
        non_finite_replacements={}
        computed_columns={}
        for index,definition in enumerate(definitions):
            column,replaced=_compute_feature_column_with_diagnostics(frame, definition)
            # Factor snapshots can contain hundreds of thousands of rows and
            # many columns.  Float32 is ample for model inputs and halves the
            # peak resident memory while the immutable snapshot is assembled.
            computed_columns[definition.slug]=column.astype("float32")
            non_finite_replacements[definition.slug]=replaced
            if (index + 1) % 5 == 0 or index + 1 == len(definitions):
                _progress(jid,10+int(65*(index+1)/len(definitions)))
        feature_columns=[d.slug for d in definitions]
        universe_columns=[column for column in ("universe_member","universe_rank") if column in frame.columns]
        output_frame=pd.DataFrame(computed_columns,index=frame.index,copy=False)
        for column in reversed(["date","symbol",*universe_columns]):
            output_frame.insert(0,column,frame[column].to_numpy(copy=False))
        del computed_columns
        profile={"features":{},"date_min":str(pd.to_datetime(frame.date).min().date()),"date_max":str(pd.to_datetime(frame.date).max().date()),"dynamic_universe":dict((version.lineage or {}).get("dynamic_universe") or {})}
        for col in feature_columns:
            values=output_frame[col];profile["features"][col]={"missing_rate":round(float(values.isna().mean()),6),"mean":_finite(values.mean()),"std":_finite(values.std()),"min":_finite(values.min()),"max":_finite(values.max()),"non_finite_replaced":non_finite_replacements[col]}
        profile["warnings"]=[
            {"code":"non_finite_replaced","feature":slug,"count":count,"message":"非有限因子值已转为空值"}
            for slug,count in non_finite_replacements.items() if count
        ]
        del frame
        payload=_parquet(output_frame);digest=hashlib.sha256(payload).hexdigest();uri=upload_bytes(f"data/features/{snap.id}/{digest[:12]}.parquet",payload,"application/vnd.apache.parquet")
        definitions_snapshot=[{"id":str(d.id),"slug":d.slug,"version":d.version,"implementation":d.implementation,"parameters":d.parameters} for d in definitions]
        with SyncSessionFactory() as s:
            row_count=len(output_frame)
            job=s.get(Job,jid);item=s.get(FeatureSnapshot,snap.id);item.status="ready";item.artifact_uri=uri;item.content_sha256=digest;item.row_count=row_count;item.profile=profile;item.lineage={"data_version_id":str(version.id),"data_sha256":version.content_sha256,"definitions":definitions_snapshot,"pipeline":"feature_registry_v2","dynamic_universe":dict((version.lineage or {}).get("dynamic_universe") or {})};job.status="succeeded";job.progress=100;job.result_summary={"snapshot_id":str(item.id),"rows":row_count,"features":feature_columns,"content_sha256":digest};job.completed_at=datetime.now(UTC);job.lease_expires_at=None;s.commit()
        return job.result_summary
    except Exception as exc:_fail(jid,str(exc),[(FeatureSnapshot,snap.id)]);raise


def _finite(value):
    """Convert numpy values to JSON-safe numbers."""

    if value is None or not np.isfinite(value):
        return None
    return round(float(value),8)


def _daily_correlation(frame,feature,method):
    values=frame[[feature,"forward_return","date"]].dropna().copy()
    if values.empty:return pd.Series(dtype=float)
    if method=="spearman":
        values[[feature,"forward_return"]]=values.groupby("date")[[feature,"forward_return"]].rank(method="average")
    values["_x2"]=values[feature]*values[feature]
    values["_y2"]=values["forward_return"]*values["forward_return"]
    values["_xy"]=values[feature]*values["forward_return"]
    daily=values.groupby("date",sort=False).agg(
        n=(feature,"size"),sx=(feature,"sum"),sy=("forward_return","sum"),
        sxx=("_x2","sum"),syy=("_y2","sum"),sxy=("_xy","sum"),
    )
    numerator=daily.n*daily.sxy-daily.sx*daily.sy
    denominator=np.sqrt((daily.n*daily.sxx-daily.sx**2)*(daily.n*daily.syy-daily.sy**2))
    result=(numerator/denominator).where((daily.n>=3)&(denominator>0)).dropna()
    return result.astype(float).reset_index(drop=True)


def _quantile_analysis(frame,feature,quantiles):
    spreads=[];top_sets=[];previous=None;turnovers=[]
    for date,group in frame[["date","symbol",feature,"forward_return"]].dropna().groupby("date"):
        if len(group)<max(3,quantiles) or group[feature].nunique()<2:continue
        effective=min(quantiles,len(group),group[feature].nunique())
        try:ranks=group[feature].rank(method="first");buckets=pd.qcut(ranks,effective,labels=False,duplicates="drop")
        except ValueError:continue
        low=group.loc[buckets==buckets.min(),"forward_return"].mean()
        high=group.loc[buckets==buckets.max(),"forward_return"].mean()
        if pd.notna(low) and pd.notna(high):spreads.append(float(high-low))
        current=set(group.loc[buckets==buckets.max(),"symbol"].astype(str))
        if previous:
            turnovers.append(1-len(previous&current)/max(1,len(previous)))
        previous=current;top_sets.append((str(pd.Timestamp(date).date()),sorted(current)))
    series=pd.Series(spreads,dtype=float)
    return {
        "observations":int(len(series)),
        "mean_spread":_finite(series.mean()),
        "annualized_spread":_finite(series.mean()*252) if len(series) else None,
        "spread_win_rate":_finite((series>0).mean()) if len(series) else None,
        "cumulative_spread":_finite((1+series).prod()-1) if len(series) else None,
        "turnover":_finite(pd.Series(turnovers,dtype=float).mean()) if turnovers else None,
    }


def research_factors(job_id:str):
    """Evaluate a feature snapshot using forward-return cross sections."""

    jid=UUID(job_id)
    with SyncSessionFactory() as s:
        job=s.get(Job,jid);run=s.get(FactorResearchRun,UUID(job.payload["factor_research_id"]))
        snapshot=s.get(FeatureSnapshot,run.snapshot_id);version=s.get(DataVersion,snapshot.data_version_id)
        job.status="running";job.started_at=datetime.now(UTC);job.attempt+=1
        job.lease_expires_at=datetime.now(UTC)+timedelta(minutes=15);run.status="running";s.commit()
    try:
        feature_frame=pd.read_parquet(io.BytesIO(download_bytes(snapshot.artifact_uri)))
        if "universe_member" in feature_frame.columns:
            feature_frame=feature_frame[feature_frame["universe_member"].fillna(False)].copy()
        market_frame=pd.read_parquet(io.BytesIO(download_bytes(version.artifact_uri)))
        feature_slugs=[item["slug"] for item in snapshot.lineage.get("definitions",[])]
        missing=[slug for slug in feature_slugs if slug not in feature_frame.columns]
        if missing:raise ValueError(f"Snapshot is missing factor columns: {', '.join(missing)}")
        market_frame["date"]=pd.to_datetime(market_frame["date"])
        feature_frame["date"]=pd.to_datetime(feature_frame["date"])
        horizon=int(run.parameters["forward_period"])
        market_frame=market_frame.sort_values(["symbol","date"])
        market_frame["forward_return"]=market_frame.groupby("symbol")["close"].shift(-horizon)/market_frame["close"]-1
        frame=feature_frame.merge(
            market_frame[["date","symbol","forward_return"]],on=["date","symbol"],how="inner"
        )
        training_fraction=float(run.parameters.get("training_fraction",.55))
        research_dates,training_boundary=factor_training_dates(frame["date"],training_fraction,horizon)
        full_date_min=str(frame["date"].min().date())
        full_date_max=str(frame["date"].max().date())
        frame=frame[frame["date"].isin(research_dates)].copy()
        _progress(jid,35)
        results={}
        min_coverage=float(run.parameters["min_coverage"])
        min_abs_rank_ic=float(run.parameters["min_abs_rank_ic"])
        min_ic_ir=float(run.parameters["min_ic_ir"])
        for index,feature in enumerate(feature_slugs):
            values=frame[feature].replace([np.inf,-np.inf],np.nan)
            coverage=float(values.notna().mean())
            ic=_daily_correlation(frame.assign(**{feature:values}),feature,"pearson")
            rank_ic=_daily_correlation(frame.assign(**{feature:values}),feature,"spearman")
            rank_ic_std=rank_ic.std()
            rank_ic_ir=float(rank_ic.mean()/rank_ic_std) if len(rank_ic)>1 and rank_ic_std else np.nan
            quantile=_quantile_analysis(frame.assign(**{feature:values}),feature,int(run.parameters["quantiles"]))
            preliminary_passed=(
                coverage>=min_coverage
                and abs(float(rank_ic.mean()))>=min_abs_rank_ic if len(rank_ic) else False
            )
            preliminary_passed=bool(preliminary_passed and abs(rank_ic_ir)>=min_ic_ir)
            significance=mean_significance(rank_ic)
            observations=significance["observations"]
            rank_ic_t_stat=significance["t_stat"]
            rank_ic_p_value=significance["p_value"]
            reasons=[]
            if coverage<min_coverage:reasons.append("覆盖率不足")
            if not len(rank_ic) or abs(float(rank_ic.mean()))<min_abs_rank_ic:reasons.append("Rank IC不足")
            if not np.isfinite(rank_ic_ir) or abs(rank_ic_ir)<min_ic_ir:reasons.append("IC稳定性不足")
            results[feature]={
                "coverage":_finite(coverage),
                "missing_rate":_finite(1-coverage),
                "ic_mean":_finite(ic.mean()),
                "ic_std":_finite(ic.std()),
                "ic_positive_rate":_finite((ic>0).mean()) if len(ic) else None,
                "rank_ic_mean":_finite(rank_ic.mean()),
                "rank_ic_std":_finite(rank_ic_std),
                "rank_ic_ir":_finite(rank_ic_ir),
                "rank_ic_observations":int(len(rank_ic)),
                "rank_ic_t_stat":_finite(rank_ic_t_stat),
                "rank_ic_p_value":_finite(rank_ic_p_value),
                "quantile":quantile,
                "preliminary_passed":preliminary_passed,
                "passed":False,
                "reasons":reasons,
            }
            _progress(jid,35+45*(index+1)/max(1,len(feature_slugs)))
        q_values=benjamini_hochberg({
            feature:metrics.get("rank_ic_p_value") for feature,metrics in results.items()
        })
        false_discovery_rate=float(run.parameters.get("false_discovery_rate",.05))
        min_ic_observations=int(run.parameters.get("min_ic_observations",30))
        selected=[]
        for feature,factor_metrics in results.items():
            q_value=q_values.get(feature)
            significant=(
                factor_metrics["rank_ic_observations"]>=min_ic_observations
                and q_value is not None and q_value<=false_discovery_rate
            )
            factor_metrics["rank_ic_q_value"]=q_value
            factor_metrics["statistically_significant"]=significant
            factor_metrics["passed"]=bool(factor_metrics.pop("preliminary_passed") and significant)
            if factor_metrics["rank_ic_observations"]<min_ic_observations:
                factor_metrics["reasons"].append("有效IC观测数不足")
            if q_value is None or q_value>false_discovery_rate:
                factor_metrics["reasons"].append("多重检验后不显著")
            if factor_metrics["passed"]:selected.append(feature)
        correlation=frame[feature_slugs].replace([np.inf,-np.inf],np.nan).corr(method="spearman")
        correlation_payload={
            left:{right:_finite(correlation.loc[left,right]) for right in feature_slugs}
            for left in feature_slugs
        }
        metrics={
            "evaluation_scope":"factor_training_only",
            "forward_period":horizon,
            "quantiles":int(run.parameters["quantiles"]),
            "sample_rows":int(len(frame)),
            "date_min":str(frame["date"].min().date()),
            "date_max":str(frame["date"].max().date()),
            "full_date_min":full_date_min,
            "full_date_max":full_date_max,
            "research_protocol":{
                "kind":"factor_training_gate_v1",
                "training_fraction":training_fraction,
                "training_boundary":str(pd.Timestamp(training_boundary).date()),
                "label_purge_days":horizon,
                "tuning_and_sealed_status":"unread",
            },
            "factors":results,
            "correlation":correlation_payload,
            "screening":{
                "selected":selected,
                "rejected":[item for item in feature_slugs if item not in selected],
                "thresholds":{
                    "min_coverage":min_coverage,
                    "min_abs_rank_ic":min_abs_rank_ic,
                    "min_ic_ir":min_ic_ir,
                    "false_discovery_rate":false_discovery_rate,
                    "min_ic_observations":min_ic_observations,
                },
                "multiple_testing":"benjamini_hochberg",
            },
        }
        with SyncSessionFactory() as s:
            job=s.get(Job,jid);item=s.get(FactorResearchRun,run.id)
            item.status="succeeded";item.metrics=metrics;item.selected_feature_slugs=selected
            job.status="succeeded";job.progress=100;job.result_summary={
                "factor_research_id":str(item.id),"selected":selected,"factor_count":len(feature_slugs)
            }
            job.completed_at=datetime.now(UTC);job.lease_expires_at=None;s.commit()
        return job.result_summary
    except Exception as exc:
        _fail(jid,str(exc),[(FactorResearchRun,run.id)]);raise
