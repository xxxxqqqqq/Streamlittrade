"""Versioned data-center and feature-registry endpoints."""

import io
from urllib.parse import quote
from uuid import UUID,uuid4
import pandas as pd
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from backend.app.core.security import get_current_user,require_admin
from backend.app.db.session import get_db_session
from backend.app.infrastructure.outbox import add_outbox
from backend.app.core.projects import ProjectContext,get_project_context
from backend.app.models.data_catalog import DataSource,DataVersion,FactorResearchRun,FeatureDefinition,FeatureSnapshot
from backend.app.models.job import Job
from backend.app.schemas.data_catalog import *
from backend.app.services.factors import factor_library_payload
from backend.app.infrastructure.object_storage import download_bytes
from backend.app.services.catalog_export import version_frame_to_csv

router=APIRouter(prefix="/data-center",tags=["data-center"],dependencies=[Depends(get_current_user)])

@router.post("/sources",response_model=SourceRead,status_code=201,dependencies=[Depends(require_admin)])
async def create_source(body:SourceCreate,session:AsyncSession=Depends(get_db_session)):
    if await session.scalar(select(DataSource).where(DataSource.slug==body.slug)):raise HTTPException(409,"source slug already exists")
    item=DataSource(**body.model_dump());session.add(item);await session.commit();await session.refresh(item);return item
@router.get("/sources",response_model=list[SourceRead])
async def sources(session:AsyncSession=Depends(get_db_session)):return list((await session.scalars(select(DataSource).order_by(DataSource.created_at))).all())
@router.post("/sync",response_model=CatalogSubmission,status_code=202)
async def sync(body:SyncCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    source=await session.get(DataSource,body.source_id)
    if not source or source.status!="active":raise HTTPException(409,"active source not found")
    jid,raw_id,standard_id=uuid4(),uuid4(),uuid4();spec=body.model_dump(mode="json")
    job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="data_sync",status="queued",progress=0,payload={**spec,"raw_version_id":str(raw_id),"standard_version_id":str(standard_id)})
    raw=DataVersion(id=raw_id,project_id=context.project.id,source_id=source.id,job_id=jid,layer="raw",status="queued",specification=spec,lineage={"provider":source.provider})
    standard=DataVersion(id=standard_id,project_id=context.project.id,source_id=source.id,parent_id=raw_id,job_id=jid,layer="standardized",status="queued",specification=spec,lineage={"parent_id":str(raw_id)})
    # Explicit flush ordering is required because these lightweight catalog
    # models intentionally avoid ORM relationships while retaining DB FKs.
    session.add(job);await session.flush()
    session.add(raw);await session.flush()
    session.add(standard);add_outbox(session,job,"backend.app.workers.data_catalog.sync_data");await session.commit()
    return CatalogSubmission(job_id=jid,resource_id=standard_id)
@router.get("/versions",response_model=list[VersionRead])
async def versions(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):return list((await session.scalars(select(DataVersion).where(DataVersion.project_id==context.project.id).order_by(DataVersion.created_at.desc()).limit(200))).all())
@router.get("/versions/{version_id}",response_model=VersionRead)
async def version_detail(version_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    item=await session.scalar(select(DataVersion).where(DataVersion.id==version_id,DataVersion.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Data version not found")
    return item
@router.get("/versions/{version_id}/download")
async def download_version_csv(version_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    """Download every immutable market row as a spreadsheet-friendly CSV."""
    item=await session.scalar(select(DataVersion).where(DataVersion.id==version_id,DataVersion.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Data version not found")
    if item.status!="ready" or not item.artifact_uri:raise HTTPException(409,"ready data version with an artifact is required")
    try:
        frame=pd.read_parquet(io.BytesIO(download_bytes(item.artifact_uri)))
        payload=version_frame_to_csv(frame)
    except Exception as exc:
        raise HTTPException(502,"Unable to prepare data version download") from exc
    title=str((item.specification or {}).get("name") or "data-version")
    filename=f"{title}-{item.layer}-{str(item.id)[:8]}.csv"
    disposition=f"attachment; filename=data-version-{str(item.id)[:8]}.csv; filename*=UTF-8''{quote(filename)}"
    return Response(payload,media_type="text/csv; charset=utf-8",headers={"Content-Disposition":disposition})
@router.get("/versions/{version_id}/artifact")
async def download_version_parquet(version_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    """Download the exact immutable Parquet artifact used by downstream research."""
    item=await session.scalar(select(DataVersion).where(DataVersion.id==version_id,DataVersion.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Data version not found")
    if item.status!="ready" or not item.artifact_uri:raise HTTPException(409,"ready data version with an artifact is required")
    try:payload=await run_in_threadpool(download_bytes,item.artifact_uri)
    except Exception as exc:raise HTTPException(502,"Unable to download data version artifact") from exc
    title=str((item.specification or {}).get("name") or "data-version")
    filename=f"{title}-{item.layer}-{str(item.id)[:8]}.parquet"
    disposition=f"attachment; filename=data-version-{str(item.id)[:8]}.parquet; filename*=UTF-8''{quote(filename)}"
    return Response(payload,media_type="application/vnd.apache.parquet",headers={"Content-Disposition":disposition})
@router.post("/features",response_model=FeatureRead,status_code=201,dependencies=[Depends(require_admin)])
async def create_feature(body:FeatureCreate,session:AsyncSession=Depends(get_db_session)):
    latest=await session.scalar(select(FeatureDefinition).where(FeatureDefinition.slug==body.slug).order_by(FeatureDefinition.version.desc()))
    item=FeatureDefinition(**body.model_dump(),version=(latest.version+1 if latest else 1));session.add(item);await session.commit();await session.refresh(item);return item
@router.get("/features",response_model=list[FeatureRead])
async def features(session:AsyncSession=Depends(get_db_session)):return list((await session.scalars(select(FeatureDefinition).order_by(FeatureDefinition.slug,FeatureDefinition.version.desc()))).all())
@router.get("/factor-library",response_model=list[FactorLibraryItem])
async def factor_library():return factor_library_payload()
@router.post("/materializations",response_model=CatalogSubmission,status_code=202)
async def materialize(body:MaterializeCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    version=await session.scalar(select(DataVersion).where(DataVersion.id==body.data_version_id,DataVersion.project_id==context.project.id))
    if not version or version.layer!="standardized" or version.status!="ready":raise HTTPException(409,"ready standardized data version required")
    ids=[str(x) for x in body.feature_definition_ids]
    found=(await session.scalars(select(FeatureDefinition).where(FeatureDefinition.id.in_(body.feature_definition_ids),FeatureDefinition.status=="active"))).all()
    if len(found)!=len(set(ids)):raise HTTPException(409,"one or more active feature definitions were not found")
    slugs=[item.slug for item in found]
    duplicate_slugs=sorted({slug for slug in slugs if slugs.count(slug)>1})
    if duplicate_slugs:
        raise HTTPException(
            409,
            "select only one version of each factor: " + ", ".join(duplicate_slugs),
        )
    jid,sid=uuid4(),uuid4();job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="feature_materialize",status="queued",progress=0,payload={"snapshot_id":str(sid)});snap=FeatureSnapshot(id=sid,project_id=context.project.id,data_version_id=version.id,job_id=jid,name=body.name,status="queued",feature_definition_ids=ids,lineage={"data_version_id":str(version.id)})
    session.add(job);await session.flush();session.add(snap);add_outbox(session,job,"backend.app.workers.data_catalog.materialize_features");await session.commit()
    return CatalogSubmission(job_id=jid,resource_id=sid)
@router.get("/materializations",response_model=list[SnapshotRead])
async def snapshots(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):return list((await session.scalars(select(FeatureSnapshot).where(FeatureSnapshot.project_id==context.project.id).order_by(FeatureSnapshot.created_at.desc()).limit(200))).all())
@router.get("/materializations/{snapshot_id}",response_model=SnapshotRead)
async def snapshot_detail(snapshot_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    item=await session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.id==snapshot_id,FeatureSnapshot.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Feature snapshot not found")
    return item
@router.get("/materializations/{snapshot_id}/artifact")
async def download_snapshot_parquet(snapshot_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    item=await session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.id==snapshot_id,FeatureSnapshot.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Feature snapshot not found")
    if item.status!="ready" or not item.artifact_uri:raise HTTPException(409,"ready feature snapshot with an artifact is required")
    try:payload=await run_in_threadpool(download_bytes,item.artifact_uri)
    except Exception as exc:raise HTTPException(502,"Unable to download feature snapshot artifact") from exc
    filename=f"{item.name}-{str(item.id)[:8]}.parquet"
    disposition=f"attachment; filename=feature-snapshot-{str(item.id)[:8]}.parquet; filename*=UTF-8''{quote(filename)}"
    return Response(payload,media_type="application/vnd.apache.parquet",headers={"Content-Disposition":disposition})
@router.post("/factor-research",response_model=CatalogSubmission,status_code=202)
async def create_factor_research(body:FactorResearchCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    snapshot=await session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.id==body.snapshot_id,FeatureSnapshot.project_id==context.project.id))
    if not snapshot or snapshot.status!="ready":raise HTTPException(409,"ready feature snapshot required")
    jid,rid=uuid4(),uuid4()
    parameters=body.model_dump(exclude={"name","snapshot_id"})
    job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="factor_research",status="queued",progress=0,payload={"factor_research_id":str(rid)})
    run=FactorResearchRun(id=rid,project_id=context.project.id,snapshot_id=snapshot.id,job_id=jid,name=body.name,status="queued",parameters=parameters,selected_feature_slugs=[])
    session.add(job);await session.flush();session.add(run);add_outbox(session,job,"backend.app.workers.data_catalog.research_factors");await session.commit()
    return CatalogSubmission(job_id=jid,resource_id=rid)
@router.get("/factor-research",response_model=list[FactorResearchRead])
async def factor_research_runs(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(FactorResearchRun).where(FactorResearchRun.project_id==context.project.id).order_by(FactorResearchRun.created_at.desc()).limit(100))).all())
@router.get("/factor-research/{research_id}",response_model=FactorResearchRead)
async def factor_research_detail(research_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    item=await session.scalar(select(FactorResearchRun).where(FactorResearchRun.id==research_id,FactorResearchRun.project_id==context.project.id))
    if item is None:raise HTTPException(404,"Factor research run not found")
    return item
