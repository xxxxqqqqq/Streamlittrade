<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {api,rootApi} from '../api'
import {errorMessage} from '../ui'
import StatusBadge from '../components/StatusBadge.vue'
import MetricValue from '../components/MetricValue.vue'
import {
  Activity,ArrowRight,Boxes,BrainCircuit,Database,FlaskConical,Layers3,RefreshCw,Sparkles,WalletCards,
} from 'lucide-vue-next'

// 首页是状态驱动的工作台，不是流程说明书：先根据项目已有什么，给出唯一
// 推荐的下一步，再补充最近产物、任务状态和数据新鲜度三块事实。
type MetricMode='rate'|'percent'|'ratio'
interface RecentAsset{
  kind:string
  name:string
  status:string|null
  created_at:string
  to:string
  metric:{mode:MetricMode;value:number|null|undefined;label:string;tone?:boolean}|null
}

const sourceLabels:Record<string,string>={
  versions:'数据版本',snapshots:'特征快照',datasets:'研究数据集',experiments:'训练实验',
  models:'模型版本',backtests:'回测记录',jobs:'计算任务',
}
const loading=ref(true),refreshing=ref(false),online=ref(false)
const failures=ref<Record<string,string>>({})
const versions=ref<any[]>([]),snapshots=ref<any[]>([])
const datasets=ref<any[]>([]),experiments=ref<any[]>([]),models=ref<any[]>([]),backtests=ref<any[]>([]),jobs=ref<any[]>([])

// 每个列表独立 try/catch：单个接口失败只影响对应区块，并把失败原因显示
// 出来，绝不静默折算成 0 或“暂无数据”。
async function request(key:string,url:string){
  try{return (await api.get(url)).data as any[]}
  catch(exception:any){failures.value={...failures.value,[key]:errorMessage(exception)};return []}
}
function hasFailure(key:string){return Boolean(failures.value[key])}

async function load(){
  loading.value=true
  failures.value={}
  try{
    try{online.value=(await rootApi.get('/health/ready')).data.status==='ready'}
    catch{online.value=false}
    const [versionRows,snapshotRows,datasetRows,experimentRows,modelRows,backtestRows,jobRows]=await Promise.all([
      request('versions','/data-center/versions'),request('snapshots','/data-center/materializations'),
      request('datasets','/datasets'),request('experiments','/experiments'),
      request('models','/models'),request('backtests','/backtests'),request('jobs','/jobs'),
    ])
    versions.value=versionRows;snapshots.value=snapshotRows;datasets.value=datasetRows
    experiments.value=experimentRows;models.value=modelRows;backtests.value=backtestRows;jobs.value=jobRows
  }finally{loading.value=false}
}
async function refresh(){refreshing.value=true;try{await load()}finally{refreshing.value=false}}
onMounted(load)

const failureList=computed(()=>Object.entries(failures.value).map(([key,message])=>`${sourceLabels[key]||key}：${message}`))
const standardized=computed(()=>versions.value.filter(item=>item.layer==='standardized'&&item.status==='ready'))
const readySnapshots=computed(()=>snapshots.value.filter(item=>item.status==='ready'))
const readyDatasets=computed(()=>datasets.value.filter(item=>item.status==='ready'))
const latestVersion=computed(()=>standardized.value[0]||null)

const metrics=computed(()=>[
  {key:'versions',label:'标准化数据版本',value:standardized.value.length,icon:Layers3},
  {key:'datasets',label:'研究数据集',value:datasets.value.length,icon:Database},
  {key:'models',label:'模型版本',value:models.value.length,icon:Boxes},
  {key:'backtests',label:'回测报告',value:backtests.value.length,icon:FlaskConical},
])
function metricText(item:{key:string;value:number}){
  if(hasFailure(item.key))return '加载失败'
  return loading.value?'—':String(item.value)
}

const nextStep=computed(()=>{
  if(!standardized.value.length)return{label:'同步第一份标准化行情',note:'项目还没有可用的标准化数据版本，先确定股票池并完成质量门禁。',action:'去数据与标的',to:'/data-center',icon:Layers3}
  if(!readySnapshots.value.length)return{label:'生成特征快照',note:'行情已就绪但还没有因子快照，没有快照就无法构建训练样本。',action:'去生成快照',to:'/data-center',icon:Sparkles}
  if(!readyDatasets.value.length)return{label:'构建研究数据集',note:'快照已就绪，把因子、标签和预测周期固化成不可变训练样本。',action:'去建数据集',to:'/datasets/new',icon:Database}
  if(!models.value.length)return{label:'训练并验证模型',note:'已有训练数据集，但还没有登记任何模型版本。',action:'去训练模型',to:'/experiments/new',icon:BrainCircuit}
  if(!backtests.value.length)return{label:'运行组合回测',note:'模型已登记，用样本外预测检验成本、收益和回撤。',action:'去回测',to:'/backtests/new',icon:FlaskConical}
  return{label:'进入模拟盘验证',note:'研究链路已经完整，可以在模拟账户上用模型信号验证交易规则。',action:'去模拟交易',to:'/paper',icon:WalletCards}
})

function stamp(value?:string|null){
  return value?new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'—'
}
function backtestName(row:any){
  if(row.signal_source==='model_oos'||row.strategy_name==='model_probability')return '模型组合回测'
  return ({right_trend:'右侧趋势策略',v_shape:'V型反转策略'} as Record<string,string>)[row.strategy_name]||row.strategy_name||'策略回测'
}
const recentAssets=computed<RecentAsset[]>(()=>{
  const items:RecentAsset[]=[
    ...datasets.value.map(item=>({kind:'数据集',name:item.name,status:item.status,created_at:item.created_at,to:'/datasets',metric:null})),
    ...experiments.value.map(item=>({kind:'训练实验',name:item.name,status:item.status,created_at:item.created_at,to:'/experiments',metric:null})),
    ...models.value.map(item=>({kind:'模型',name:item.name,status:item.stage,created_at:item.created_at,to:`/models/${item.id}`,
      metric:{mode:'rate' as MetricMode,value:item.metrics?.roc_auc,label:'ROC AUC'}})),
    ...backtests.value.map(item=>({kind:'回测',name:backtestName(item),status:null,created_at:item.created_at,to:`/backtests/${item.id}`,
      metric:{mode:'percent' as MetricMode,value:item.metrics?.total_return,label:'累计收益',tone:true}})),
  ]
  return items
    .filter(item=>Boolean(item.created_at))
    .sort((left,right)=>new Date(right.created_at).getTime()-new Date(left.created_at).getTime())
    .slice(0,5)
})

const runningJobs=computed(()=>jobs.value.filter(item=>['queued','running','cancel_requested'].includes(item.status)).slice(0,4))
const failedJobs=computed(()=>jobs.value.filter(item=>item.status==='failed').slice(0,4))
const succeededJobs=computed(()=>jobs.value.filter(item=>item.status==='succeeded').slice(0,4))
function jobTarget(job:any){
  const summary=job.result_summary||{}
  if(summary.standard_version_id)return{to:`/data-center/versions/${summary.standard_version_id}`,label:'查看数据版本'}
  if(summary.snapshot_id)return{to:`/data-center/snapshots/${summary.snapshot_id}`,label:'查看特征快照'}
  if(summary.factor_research_id)return{to:'/factor-research',label:'查看因子研究'}
  if(summary.dataset_id)return{to:'/datasets',label:'查看数据集'}
  if(summary.model_id)return{to:`/models/${summary.model_id}`,label:'查看模型'}
  if(summary.experiment_id)return{to:'/experiments',label:'查看实验'}
  if(summary.prediction_id)return{to:'/predictions',label:'查看预测产物'}
  if(summary.run_id)return{to:'/paper',label:'查看模拟盘审计'}
  return{to:'/jobs',label:'去任务中心'}
}

const freshness=computed(()=>{
  const version=latestVersion.value
  if(!version)return null
  return{
    id:version.id,
    start:version.specification?.start_date||'—',
    end:version.specification?.end_date||'—',
    rows:version.row_count,
    symbols:version.quality_report?.symbol_count??version.specification?.symbols?.length??null,
    created:version.created_at,
    hash:version.content_sha256?String(version.content_sha256).slice(0,12):null,
  }
})
</script>

<template>
  <section>
    <div class="hero research-hero">
      <div><span class="eyebrow">STATUS DRIVEN WORKSPACE</span><h2>先看项目状态，再决定做什么</h2><p>平台根据已有的数据版本、因子快照、数据集、模型和回测，给出唯一推荐的下一步。</p></div>
      <div class="system-pill" :class="{online}"><span></span>{{online?'研究服务正常':'正在连接服务'}}</div>
    </div>

    <p v-if="failureList.length" class="error-box">部分数据加载失败（其余区块按已返回的数据展示，结果可能不完整）：{{failureList.join('；')}}</p>

    <article class="panel next-step">
      <div class="next-step-icon"><component :is="nextStep.icon" :size="22"/></div>
      <div><small>下一步</small><h3>{{nextStep.label}}</h3><p>{{nextStep.note}}</p></div>
      <RouterLink class="primary link-button" :to="nextStep.to">{{nextStep.action}}<ArrowRight :size="15"/></RouterLink>
    </article>

    <div class="metric-grid">
      <article v-for="item in metrics" :key="item.key" class="metric">
        <div class="metric-icon"><component :is="item.icon" :size="20"/></div>
        <div><small>{{item.label}}</small><strong :class="{stale:hasFailure(item.key)}">{{metricText(item)}}</strong></div>
      </article>
    </div>

    <div class="dashboard-grid">
      <article class="panel">
        <div class="panel-head"><div><h3>最近产物</h3><p>数据集、实验、模型和回测按时间混排</p></div><button class="secondary" :disabled="refreshing" @click="refresh"><RefreshCw :size="15" :class="{spin:refreshing}"/>刷新</button></div>
        <div class="timeline">
          <RouterLink v-for="item in recentAssets" :key="item.to+item.created_at" class="timeline-row" :to="item.to">
            <span class="timeline-kind">{{item.kind}}</span>
            <div><b>{{item.name}}</b><small>{{stamp(item.created_at)}}</small></div>
            <StatusBadge v-if="item.status" :status="item.status"/>
            <MetricValue v-if="item.metric" :value="item.metric.value" :mode="item.metric.mode" :tone="item.metric.tone"/>
            <ArrowRight :size="14"/>
          </RouterLink>
          <div v-if="!recentAssets.length&&!loading" class="empty">还没有研究产物，请从数据与标的开始。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h3>数据新鲜度</h3><p>最近一次标准化数据版本</p></div><Layers3 :size="18"/></div>
        <div v-if="hasFailure('versions')" class="empty">数据版本加载失败，无法判断数据新鲜度。</div>
        <template v-else-if="freshness">
          <dl class="freshness-list">
            <div><dt>覆盖区间</dt><dd>{{freshness.start}} → {{freshness.end}}</dd></div>
            <div><dt>行数 / 标的</dt><dd>{{freshness.rows??'—'}} / {{freshness.symbols??'—'}}</dd></div>
            <div><dt>登记时间</dt><dd>{{stamp(freshness.created)}}</dd></div>
            <div><dt>内容 SHA</dt><dd><code>{{freshness.hash||'—'}}</code></dd></div>
          </dl>
          <RouterLink class="text-button freshness-panel-link" :to="`/data-center/versions/${freshness.id}`">查看数据质量详情<ArrowRight :size="13"/></RouterLink>
        </template>
        <div v-else class="empty">还没有标准化数据版本，请先同步行情。</div>
      </article>
    </div>

    <article class="panel">
      <div class="panel-head"><div><h3>任务状态</h3><p>运行中的计算、失败原因和刚完成的产出</p></div><RouterLink to="/jobs">进入任务中心</RouterLink></div>
      <div v-if="hasFailure('jobs')" class="empty">任务列表加载失败，无法判断后台计算状态。</div>
      <template v-else>
        <div v-if="runningJobs.length" class="job-block">
          <h4><Activity :size="15"/>运行中</h4>
          <div v-for="job in runningJobs" :key="job.id" class="job-line">
            <b>{{job.kind}}</b><StatusBadge :status="job.status"/><span class="job-progress-text">{{Math.round(job.progress)}}%</span><small>{{stamp(job.created_at)}}</small>
          </div>
        </div>
        <div v-if="failedJobs.length" class="job-block">
          <h4 class="danger">失败</h4>
          <div v-for="job in failedJobs" :key="job.id" class="job-line">
            <b>{{job.kind}}</b><StatusBadge :status="job.status"/><span class="failure-reason" :title="job.error_message||'未记录失败原因'">{{job.error_message||'未记录失败原因'}}</span><small>{{stamp(job.created_at)}}</small>
          </div>
        </div>
        <div v-if="succeededJobs.length" class="job-block">
          <h4>最近完成</h4>
          <div v-for="job in succeededJobs" :key="job.id" class="job-line">
            <b>{{job.kind}}</b><StatusBadge :status="job.status"/>
            <RouterLink class="job-target" :to="jobTarget(job).to">{{jobTarget(job).label}}<ArrowRight :size="13"/></RouterLink><small>{{stamp(job.created_at)}}</small>
          </div>
        </div>
        <div v-if="!runningJobs.length&&!failedJobs.length&&!succeededJobs.length" class="empty">暂无计算任务，请从数据与标的开始。</div>
      </template>
    </article>
  </section>
</template>

<style scoped>
.next-step{display:flex;align-items:center;gap:16px;margin:16px 0}.next-step-icon{width:46px;height:46px;flex:none;border-radius:12px;background:#e8f3ff;color:#1768d7;display:grid;place-items:center}.next-step>div:nth-child(2){min-width:0;flex:1}.next-step small{color:#1768d7;font-size:10px;font-weight:700;letter-spacing:1px}.next-step h3{font:700 17px Manrope;margin:5px 0 4px}.next-step p{margin:0;color:#7f8b9c;font-size:12px;line-height:1.6}.next-step .link-button{flex:none}.metric .stale{font-size:15px;color:#b73842}.timeline{margin-top:8px}.timeline-row{display:flex;align-items:center;gap:12px;padding:13px 4px;border-top:1px solid #edf0f4;color:inherit;text-decoration:none}.timeline-row:hover{background:#f7fafd}.timeline-kind{width:62px;flex:none;color:#8793a3;font-size:10px;font-weight:700;letter-spacing:.5px}.timeline-row>div{min-width:0;flex:1}.timeline-row b,.timeline-row small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.timeline-row b{color:#2f4057;font-size:13px}.timeline-row small{margin-top:4px;color:#8b97a7;font-size:10px}.timeline-row>.metric-value{flex:none;color:#34455b;font-size:12px;font-weight:700}.timeline-row>svg{color:#a1adbb}.freshness-list{margin:12px 0 0}.freshness-list div{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-top:1px solid #edf0f4;font-size:12px}.freshness-list dt{color:#7c8999}.freshness-list dd{margin:0;font-weight:600;overflow-wrap:anywhere}.freshness-list code{font-size:11px}.freshness-panel-link{width:fit-content;margin-top:10px;text-decoration:none}.job-block{margin-top:14px}.job-block h4{display:flex;align-items:center;gap:6px;margin:0 0 6px;color:#526176;font-size:11px;font-weight:700}.job-block h4.danger{color:#b73842}.job-line{display:flex;align-items:center;gap:10px;padding:11px 4px;border-top:1px solid #edf0f4;font-size:12px}.job-line b{min-width:130px;color:#35445a;font-size:12px}.job-line small{margin-left:auto;color:#8b97a7;font-size:10px}.job-progress-text{color:#5d6b7f;font-weight:700}.failure-reason{min-width:0;flex:1;overflow:hidden;color:#c3494f;text-overflow:ellipsis;white-space:nowrap}.job-target{margin-left:auto;display:flex;align-items:center;gap:4px;color:#1768d7;font-size:11px;text-decoration:none}.job-target+small{margin-left:12px}@media(max-width:900px){.next-step{align-items:flex-start;flex-wrap:wrap}.next-step .link-button{margin-left:62px}.job-line{flex-wrap:wrap}.failure-reason{flex-basis:100%}.job-line b{min-width:0}.job-target{margin-left:0}}
</style>
