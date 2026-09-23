<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {api} from '../api'
import {useRouter} from 'vue-router'
import Paginator from '../components/Paginator.vue'
import StatusBadge from '../components/StatusBadge.vue'
import MetricValue from '../components/MetricValue.vue'
import SectionTabs from '../components/SectionTabs.vue'
import GuideCard from '../components/GuideCard.vue'
import VerdictBadge from '../components/VerdictBadge.vue'
import {backtestTabs,trainingTabs} from '../sections'
import {statusLabel} from '../status'
import {excessReturnVerdict,rankIcVerdict,rocAucVerdict,selectionVerdict} from '../verdict'
import {BrainCircuit,Download,Eye,GitBranch,Plus,RefreshCw,Search,Sparkles} from 'lucide-vue-next'
import {downloadApiFile} from '../download'
const props=defineProps<{kind:string}>(),router=useRouter()
const rows=ref<any[]>([]),loading=ref(false),query=ref(''),statusFilter=ref(''),page=ref(1),pageSize=ref(20)
const models=ref<any[]>([]),experiments=ref<any[]>([]),datasets=ref<any[]>([])
const datasetDownloadId=ref(''),datasetDownloadError=ref('')
const labels:any={backtests:['回测中心','查看模型组合或规则策略在历史行情中的表现'],datasets:['研究数据集','把因子和答案（未来涨跌）对齐后的表格，训练只读这里'],models:['模型仓库','每个模型都写清这次训练在学什么、学得好不好'],strategies:['策略版本','维护策略定义和参数版本'],jobs:['计算任务','监控排队、运行和失败任务']}
// 每段列表页顶部的一句话说明卡：回答"这一步在干什么"。
const createLabels:any={datasets:'新建研究数据集',backtests:'新建回测'}
const guides:any={
  backtests:{title:'这一步在干什么',text:'用模型没见过的数据模拟真实买卖（T+1、整手、手续费全算），看赚不赚钱。'},
  datasets:{title:'这一步在干什么',text:'训练数据 = 因子表 + 答案（未来涨跌）。数据集一旦生成就不可修改，训练只读它。'},
  models:{title:'这一步在干什么',text:'训练产出的模型放在这里：看它的预测能力、选股区分度，再决定要不要回测和上线。'},
}
// 同一个列表组件同时服务训练段和回测段，页签跟着 kind 走：用户在任何一张
// 列表里都能看清自己处在五段流的哪一段。
const tabs=computed(()=>props.kind==='backtests'?backtestTabs:props.kind==='datasets'||props.kind==='models'?trainingTabs:null)
const matching=computed(()=>rows.value.filter(item=>(!query.value||JSON.stringify(item).toLowerCase().includes(query.value.toLowerCase()))&&(!statusFilter.value||(item.status||item.stage)===statusFilter.value)))
const paged=computed(()=>matching.value.slice((page.value-1)*pageSize.value,page.value*pageSize.value))
const availableStatuses=computed(()=>[...new Set(rows.value.map(item=>item.status||item.stage).filter(Boolean))])
async function load(option:boolean|PointerEvent=false){
  const silent=typeof option==='boolean'&&option
  if(!silent)loading.value=true
  try{
    rows.value=(await api.get('/'+props.kind)).data
    models.value=props.kind==='backtests'?(await api.get('/models')).data:[]
    // 模型卡片要说清"这次训练在学什么"：因子数和预测周期记在数据集上，列表
    // 接口不回这两项，所以模型页额外取一次实验与数据集做关联。
    if(props.kind==='models'){
      const [experimentResponse,datasetResponse]=await Promise.all([api.get('/experiments'),api.get('/datasets')])
      experiments.value=experimentResponse.data;datasets.value=datasetResponse.data
    }
  }finally{loading.value=false}
}
let timer:number|undefined
onMounted(()=>{load();timer=window.setInterval(()=>{if(props.kind==='jobs')load(true)},5000)})
onUnmounted(()=>window.clearInterval(timer))
watch(()=>props.kind,()=>{page.value=1;load()});watch([query,statusFilter],()=>page.value=1)
const columns=computed(()=>({backtests:['symbol','strategy_name','metrics','created_at'],datasets:['name','status','row_count','created_at'],models:['name','stage','algorithm','created_at'],strategies:['name','slug','version','created_at'],jobs:['kind','status','progress','created_at']} as any)[props.kind])
function display(value:any){if(value===null||value===undefined)return '—';if(typeof value==='object')return JSON.stringify(value).slice(0,70);if(String(value).includes('T'))return new Date(value).toLocaleString();return value}
function create(){if(props.kind==='datasets')router.push('/datasets/new');else if(props.kind==='backtests')router.push('/backtests/new')}
async function downloadDataset(row:any){
  if(datasetDownloadId.value)return
  datasetDownloadId.value=row.id;datasetDownloadError.value=''
  try{await downloadApiFile(`/datasets/${row.id}/artifact`,`research-dataset-${String(row.id).slice(0,8)}.parquet`)}
  catch(exception:any){datasetDownloadError.value=exception.message||'下载失败，请稍后重试'}
  finally{datasetDownloadId.value=''}
}
function isModelBacktest(row:any){return row.signal_source==='model_oos'||row.strategy_name==='model_probability'}
function symbols(row:any){return String(row.symbol||'').split(',').map((item:string)=>item.trim()).filter(Boolean)}
function universeSize(row:any){
  const recorded=Number(row.data_quality?.symbol_count)
  return Number.isFinite(recorded)&&recorded>0?recorded:symbols(row).length
}
function universeName(row:any){return isModelBacktest(row)?'模型候选股票池':(symbols(row).slice(0,3).join(' · ')||'未指定标的')}
function universeDescription(row:any){
  const count=universeSize(row)
  return isModelBacktest(row)?`${count||'—'} 只股票参与横截面选股`:(count>3?`等 ${count} 只股票`:`${count||0} 只股票`)
}
function modelName(row:any){
  const item=models.value.find(model=>model.id===row.model_id)
  return item?.name||`模型 ${String(row.model_id||'').slice(0,8)}`
}
function portfolioRules(row:any){
  const construction=row.portfolio_construction||{},parameters=row.strategy_parameters||{}
  const topN=construction.top_n??parameters.top_n
  const probability=construction.minimum_probability??parameters.minimum_probability
  const frequency=construction.rebalance_frequency??parameters.rebalance_frequency
  if(topN===undefined||probability===undefined||frequency===undefined)return '组合规则未记录'
  return `Top-${topN} · 概率 ≥ ${Number(probability).toFixed(2)} · ${frequency} 日调仓`
}
function strategyLabel(row:any){
  if(row.signal_source==='model_oos'||row.strategy_name==='model_probability'){
    return row.portfolio_construction?.prediction_scope==='sealed_oos'?'终检（一次性）模型信号':'验证区模型信号'
  }
  return ({right_trend:'右侧趋势策略',v_shape:'V型反转策略'} as Record<string,string>)[row.strategy_name]||row.strategy_name||'未命名策略'
}
function metric(row:any,key:string){
  const value=row.metrics?.[key]
  return typeof value==='number'&&Number.isFinite(value)?value:null
}
// 回测结论统一走判断层：超额收益按小数口径传入，成交为 0 时按"全现金"处理。
function tradeCount(row:any){
  const value=row.metrics?.turnover_events??row.metrics?.total_trades
  return typeof value==='number'&&Number.isFinite(value)?value:null
}
function backtestVerdict(row:any){
  const trades=tradeCount(row)
  const excess=metric(row,'excess_return')
  return selectionVerdict(trades===null?true:trades>0)??excessReturnVerdict(excess===null?null:excess/100,trades)
}
// 模型卡片：把训练时用的因子数、预测周期、验证折数摊开，说明这次训练在学什么。
function datasetForModel(row:any){
  const experiment=experiments.value.find(item=>item.id===row.experiment_id)
  return datasets.value.find(item=>item.id===experiment?.dataset_id)
}
function modelBrief(row:any){
  const dataset=datasetForModel(row)
  return {
    factors:dataset?.feature_count??null,
    horizon:dataset?.specification?.horizon??null,
    dataset:dataset?.name||'数据集已删除',
  }
}
function period(row:any){return row.start_date&&row.end_date?`${row.start_date} → ${row.end_date}`:'回测区间未记录'}
function createdAt(value:any){return value?new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'—'}
const modelStages=computed(()=>({
  production:rows.value.filter(item=>item.stage==='production').length,
  validated:rows.value.filter(item=>item.stage==='validated').length,
  candidate:rows.value.filter(item=>item.stage==='candidate').length,
}))
function modelDatasetHash(row:any){return row.reproducibility?.dataset?.content_sha256?.slice(0,12)||'未记录'}
// 预选模型后跳转，目标页会按该模型预填表单，否则用户要重新挑一遍。
function predict(row:any){router.push({path:'/predictions',query:{model_id:row.id}})}
</script>
<template>
  <section>
    <SectionTabs v-if="tabs" :tabs="tabs"/>
    <GuideCard v-if="guides[kind]" :icon="BrainCircuit" :title="guides[kind].title" :text="guides[kind].text"/>
    <div class="page-intro" :class="{'model-page-intro':kind==='models'}">
      <div><h2>{{labels[kind][0]}}</h2><p>{{labels[kind][1]}}</p></div>
      <button v-if="['datasets','backtests'].includes(kind)" class="primary" @click="create"><Plus :size="16"/>{{createLabels[kind]}}</button>
    </div>
    <article class="panel records" :class="{'model-records':kind==='models'}">
      <div class="toolbar" :class="{'model-toolbar':kind==='models'}">
        <label class="toolbar-search"><Search :size="17"/><input v-model="query" placeholder="搜索名称、状态或标识"/></label>
        <div class="toolbar-controls">
          <label class="toolbar-select"><span>状态筛选</span><select v-model="statusFilter"><option value="">全部状态</option><option v-for="value in availableStatuses" :key="value" :value="value">{{statusLabel(value)}}</option></select></label>
          <label class="toolbar-select"><span>每页显示</span><select v-model.number="pageSize"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select></label>
        </div>
        <button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button>
      </div>

      <div v-if="kind==='backtests'" class="backtest-list">
        <div class="backtest-row backtest-header"><span>股票池</span><span>信号来源</span><span>核心指标</span><span>判断</span><span>回测区间</span><span>操作</span></div>
        <article v-for="row in paged" :key="row.id" class="backtest-row backtest-item">
          <div class="universe-cell">
            <b>{{universeName(row)}}</b>
            <small>{{universeDescription(row)}}</small>
          </div>
          <div class="signal-cell">
            <b>{{strategyLabel(row)}}</b>
            <small><i class="run-type" :class="row.signal_source">{{row.signal_source==='model_oos'?'模型预测':'策略规则'}}</i>{{row.run_type==='portfolio'?'组合回测':'单标的回测'}}<template v-if="isModelBacktest(row)"> · {{modelName(row)}} · {{portfolioRules(row)}}</template></small>
          </div>
          <div class="performance-cell">
            <span><small>累计收益</small><MetricValue :value="metric(row,'total_return')" mode="percent" tone/></span>
            <span><small>超额收益</small><MetricValue :value="metric(row,'excess_return')" mode="percent" tone/></span>
            <span><small>最大回撤</small><MetricValue :value="metric(row,'max_drawdown')" mode="percent"/></span>
          </div>
          <div class="verdict-cell"><VerdictBadge :verdict="backtestVerdict(row)"/><small>vs 等权基准</small></div>
          <div class="date-cell"><b>{{period(row)}}</b><small>创建于 {{createdAt(row.created_at)}}</small></div>
          <div class="backtest-action"><button class="text-button" @click="router.push('/backtests/'+row.id)"><Eye :size="14"/>查看报告</button></div>
        </article>
        <div v-if="!matching.length&&!loading" class="empty">还没有回测：在「新建回测中心」用模型信号或策略版本发起一次，报告会出现在这里。</div>
      </div>

      <div v-else-if="kind==='models'" class="model-list">
        <div class="model-stage-summary">
          <div><small>生产模型</small><b>{{modelStages.production}}</b><i class="production"></i></div>
          <div><small>已验证模型</small><b>{{modelStages.validated}}</b><i class="validated"></i></div>
          <div><small>候选模型</small><b>{{modelStages.candidate}}</b><i class="candidate"></i></div>
          <p><GitBranch :size="14"/>模型版本、数据血缘与样本外验证结果统一管理</p>
        </div>
        <article v-for="row in paged" :key="row.id" class="model-row">
          <div class="model-identity">
            <div class="model-icon"><BrainCircuit :size="19"/></div>
            <div><b>{{row.name}}</b><small>{{row.algorithm}} · v{{row.version}} · 创建于 {{createdAt(row.created_at)}}</small></div>
          </div>
          <div class="model-stage-cell"><StatusBadge :status="row.stage"/><small>{{row.prediction_artifact_uri?'已具备批量预测产物':'暂未生成预测产物'}}</small></div>
          <div class="model-metrics">
            <span><small>预测能力（ROC AUC）</small><MetricValue :value="metric(row,'roc_auc')"/><VerdictBadge :verdict="rocAucVerdict(metric(row,'roc_auc'))"/></span>
            <span><small>选股区分度（Rank IC）</small><MetricValue :value="metric(row,'rank_ic')" mode="ratio" :digits="3"/><VerdictBadge :verdict="rankIcVerdict(metric(row,'rank_ic'))"/></span>
            <span><small>成本后收益（研究口径估算）</small><MetricValue :value="metric(row,'cost_adjusted_return')" tone/></span>
            <span><small>年化夏普</small><MetricValue :value="metric(row,'annualized_sharpe')" mode="ratio" :digits="2"/></span>
          </div>
          <div class="model-brief">
            <b>这次训练在学什么</b>
            <span>用 {{modelBrief(row).factors??'—'}} 个因子预测 {{modelBrief(row).horizon??'—'}} 个交易日后的涨跌</span>
            <span>训练数据：{{modelBrief(row).dataset}}</span>
            <span>{{row.metrics?.fold_count??row.metrics?.folds?.length??0}} 折时间序列验证 · 训练数据 SHA {{modelDatasetHash(row)}}</span>
            <span class="model-brief-link">训练区间与模型没见过的打分区间见模型详情</span>
          </div>
          <div class="model-actions"><button class="text-button" @click="router.push('/models/'+row.id)"><Eye :size="14"/>查看模型</button><button class="secondary compact" :disabled="!row.prediction_artifact_uri" @click="predict(row)"><Sparkles :size="13"/>预测</button></div>
        </article>
        <div v-if="!matching.length&&!loading" class="empty">还没有模型版本：先准备训练数据并跑完一次训练实验。</div>
      </div>

      <div v-else-if="kind==='datasets'" class="data-table">
        <p v-if="datasetDownloadError" class="error-box dataset-download-error">{{datasetDownloadError}}</p>
        <div class="data-row header with-action"><span>名称</span><span>状态</span><span>行数</span><span>创建时间</span><span>操作</span></div>
        <div v-for="row in paged" :key="row.id" class="data-row with-action">
          <span>{{row.name}}</span><span><StatusBadge :status="row.status"/></span><span>{{display(row.row_count)}}</span><span>{{display(row.created_at)}}</span>
          <span><button class="text-button" :disabled="row.status!=='ready'||!row.artifact_uri||Boolean(datasetDownloadId)" @click="downloadDataset(row)"><Download :size="14"/>{{datasetDownloadId===row.id?'正在下载…':'下载 Parquet'}}</button></span>
        </div>
        <div v-if="!matching.length&&!loading" class="empty">还没有研究数据集：先在数据中心准备因子快照，再把因子和答案（未来涨跌）对齐成训练数据。</div>
      </div>

      <div v-else class="data-table">
        <div class="data-row header"><span v-for="column in columns" :key="column">{{column.replace('_',' ')}}</span></div>
        <div v-for="row in paged" :key="row.id" class="data-row"><span v-for="column in columns" :key="column"><StatusBadge v-if="column==='status'||column==='stage'" :status="row[column]"/><template v-else>{{display(row[column])}}</template></span></div>
        <div v-if="!matching.length&&!loading" class="empty">暂无记录。这个列表由平台的异步任务写入，发起对应任务后会自动出现。</div>
      </div>
      <Paginator :page="page" :total="matching.length" :page-size="pageSize" @change="value=>page=value"/>
    </article>
  </section>
</template>

<style scoped>
.backtest-row{display:grid;grid-template-columns:1fr .95fr 1.7fr .8fr .9fr .6fr;gap:16px;align-items:center;padding:15px 22px;border-top:1px solid #edf0f4}.backtest-header{border-top:0;background:#f8fafc;color:#8390a1;font-size:10px;font-weight:700;letter-spacing:.55px;text-transform:uppercase}.backtest-item{min-height:96px;transition:background .16s}.backtest-item:hover{background:#fbfdff}.universe-cell b,.signal-cell b,.date-cell b{display:block;color:#35445a;font-size:12px;line-height:1.45}.universe-cell small,.signal-cell small,.date-cell small{display:block;margin-top:4px;color:#8b97a7;font-size:10px}.run-type{display:inline-block;margin-right:6px;padding:3px 6px;border-radius:8px;background:#edf0f5;color:#647387;font-size:8px;font-style:normal;font-weight:700}.run-type.model_oos{background:#e8f1ff;color:#1768d7}.performance-cell{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.performance-cell span{min-width:0;padding:8px 9px;border:1px solid #e7ecf2;border-radius:7px;background:#fafbfd;color:#3c4b60}.performance-cell small,.performance-cell .metric-value{display:block}.performance-cell small{overflow:hidden;color:#8b97a7;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.performance-cell .metric-value{margin-top:4px;font-size:11px;font-weight:700}.backtest-action{display:flex;justify-content:flex-end}.backtest-action .text-button{white-space:nowrap}.records :deep(.paginator){border-top:1px solid #edf0f4}@media(max-width:1040px){.backtest-list{overflow:auto}.backtest-row{min-width:930px}}@media(max-width:720px){.backtest-row{padding-left:15px;padding-right:15px}.toolbar{gap:8px;flex-wrap:wrap}.toolbar label{flex:1}.toolbar input{width:100%}}
.dataset-download-error{margin:12px 18px}.data-row.with-action .text-button{white-space:nowrap}
.toolbar-search{display:flex;align-items:center;gap:8px;min-width:280px}.toolbar-controls{display:flex;align-items:center;gap:10px;margin-left:auto}.toolbar .toolbar-select{display:flex;align-items:center;gap:7px;margin:0;padding:0;border:0;background:transparent;color:#738096}.toolbar-select span{font-size:11px;font-weight:700;white-space:nowrap}.toolbar-select select{height:38px;min-width:126px;padding:0 28px 0 11px;border:1px solid #d8e1ec;border-radius:8px;background:#fff;color:#34445a;font-size:13px;font-weight:600;outline:0}.toolbar-select select:focus{border-color:#2877dd;box-shadow:0 0 0 3px #2877dd12}.model-page-intro h2{font-size:23px}.model-page-intro p{font-size:14px;line-height:1.6}.model-toolbar{padding:18px 26px!important;background:linear-gradient(90deg,#fbfdff,#fff)}.model-toolbar .toolbar-search{height:44px;min-width:390px;border-radius:10px}.model-toolbar .toolbar-search input{height:42px;font-size:14px}.model-toolbar .secondary{height:42px;padding:0 14px;font-size:13px}.model-stage-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:18px 26px;border-bottom:1px solid #e8edf3;background:#fafbfd}.model-stage-summary>div{position:relative;padding:11px 13px;border:1px solid #e0e7ef;border-radius:10px;background:#fff}.model-stage-summary small,.model-stage-summary b{display:block}.model-stage-summary small{color:#7f8d9f;font-size:11px}.model-stage-summary b{margin-top:5px;color:#2f4057;font-size:20px}.model-stage-summary i{position:absolute;right:13px;top:16px;width:8px;height:8px;border-radius:50%;background:#a2adbb}.model-stage-summary i.production{background:#1bb281}.model-stage-summary i.validated{background:#2578dd}.model-stage-summary i.candidate{background:#9d7aeb}.model-stage-summary p{grid-column:1/-1;display:flex;align-items:center;gap:7px;margin:2px 0 0;color:#718096;font-size:11px}.model-row{display:grid;grid-template-columns:minmax(210px,1.1fr) 110px minmax(320px,1.4fr) minmax(200px,1fr) 118px;gap:16px;align-items:center;padding:20px 26px;border-top:1px solid #edf0f4;transition:background .16s}.model-row:hover{background:#fbfdff}.model-identity{display:flex;align-items:center;gap:12px;min-width:0}.model-icon{width:42px;height:42px;flex:none;border-radius:11px}.model-identity b,.model-identity small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.model-identity b{color:#2f4057;font-size:14px}.model-identity small{margin-top:5px;color:#7f8d9f;font-size:11px}.model-stage-cell .status{font-size:11px;padding:5px 9px}.model-stage-cell small{display:block;margin-top:8px;color:#7f8d9f;font-size:10px;line-height:1.45}.model-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.model-metrics span{min-width:0;padding:10px;border:1px solid #e2e8f0;border-radius:9px;background:#fafbfd;color:#34455b}.model-metrics small,.model-metrics .metric-value{display:block}.model-metrics small{overflow:hidden;color:#8290a2;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.model-metrics .metric-value{margin-top:5px;font-size:13px;font-weight:700}.model-brief b,.model-brief span{display:block}.model-brief b{color:#4f46e5;font-size:9px}.model-brief span{margin-top:5px;color:#5b6474;font-size:10px;line-height:1.45}.model-brief-link{color:#98a0ae!important}.model-actions{display:flex;flex-direction:column;align-items:stretch;justify-content:center;gap:7px}.secondary.compact{height:34px;justify-content:center;padding:0 9px;font-size:10px}.model-actions .text-button{justify-content:center;font-size:11px;white-space:nowrap}.verdict-cell{display:flex;flex-direction:column;align-items:flex-start;gap:5px}.verdict-cell small{color:#8b97a7;font-size:9px}.model-metrics .verdict-badge{margin-top:5px}@media(max-width:1280px){.model-row{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:'identity stage' 'metrics metrics' 'brief brief' 'actions actions'}.model-identity{grid-area:identity}.model-stage-cell{grid-area:stage}.model-metrics{grid-area:metrics}.model-brief{grid-area:brief}.model-actions{grid-area:actions;flex-direction:row;align-items:center}.model-actions .secondary.compact{height:34px}}@media(max-width:720px){.toolbar-controls{width:100%;margin-left:0}.toolbar .toolbar-select{flex:1}.toolbar-select select{min-width:0;width:100%}.model-toolbar{padding:15px!important}.model-toolbar .toolbar-search{min-width:0;width:100%}.model-stage-summary{grid-template-columns:1fr;padding:15px}.model-stage-summary p{display:none}.model-row{grid-template-columns:1fr;grid-template-areas:'identity' 'stage' 'metrics' 'brief' 'actions';padding:18px 15px}.model-actions{justify-content:flex-start}.model-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
