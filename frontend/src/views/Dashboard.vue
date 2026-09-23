<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import type {Component} from 'vue'
import {api} from '../api'
import {user} from '../auth'
import {jobKindLabel,jobSectionLabel,jobTarget} from '../jobs'
import {errorMessage} from '../ui'
import {statusLabel} from '../status'
import {excessReturnVerdict,rankIcVerdict,rocAucVerdict,type Verdict,type VerdictLevel} from '../verdict'
import StatusBadge from '../components/StatusBadge.vue'
import VerdictBadge from '../components/VerdictBadge.vue'
import {
  ArrowRight,BrainCircuit,Database,Download,Filter,FlaskConical,RefreshCw,RotateCcw,Sparkles,WalletCards,
} from 'lucide-vue-next'

// 首页是“我的研究控制台”：顶上五段流水线状态一屏看完，中间只给一个下一步，
// 下面拆成最近动态与需要关注。这里不重复各段页面已有的详情表格。
interface StageCard{
  key:string;no:string;label:string;icon:Component;to:string;ready:boolean
  title:string;note:string;time:string
  verdict:Verdict|null
  status:string|null;statusLabel?:string
}
interface ActivityItem{key:string;status:string;title:string;detail:string;time:string;to:string;toLabel?:string}
interface AttentionItem{key:string;level:VerdictLevel;label:string;title:string;detail:string;time:string;to?:string;action?:string;retry?:string}

const loading=ref(true),failures=ref<Record<string,string>>({}),retrying=ref(''),actionError=ref('')
const versions=ref<any[]>([]),snapshots=ref<any[]>([]),factorRuns=ref<any[]>([]),datasets=ref<any[]>([])
const experiments=ref<any[]>([]),models=ref<any[]>([]),backtests=ref<any[]>([]),jobs=ref<any[]>([]),paperAccounts=ref<any[]>([])

// 每个接口独立 try/catch：单个列表失败只影响对应区块，并把失败原因显示出来，
// 绝不静默折算成 0 或“暂无数据”。
async function request(label:string,url:string){
  try{return (await api.get(url)).data as any[]}
  catch(exception:any){failures.value={...failures.value,[label]:errorMessage(exception)};return []}
}
function hasFailure(label:string){return Boolean(failures.value[label])}
// 某一段的接口挂了，就不该说“还没有产物”，那是两回事：前者是加载失败。
function missingTitle(labels:string[],fallback:string){
  if(labels.some(label=>hasFailure(label)))return '数据加载失败'
  return loading.value?'正在加载…':fallback
}

async function load(){
  loading.value=true
  failures.value={}
  try{
    const [versionRows,snapshotRows,factorRows,datasetRows,experimentRows,modelRows,backtestRows,jobRows,accountRows]=await Promise.all([
      request('数据版本','/data-center/versions'),request('因子快照','/data-center/materializations'),
      request('因子检验','/data-center/factor-research'),request('训练数据','/datasets'),
      request('训练实验','/experiments'),request('模型','/models'),request('回测','/backtests'),
      request('任务','/jobs'),request('模拟盘','/paper/accounts'),
    ])
    versions.value=versionRows;snapshots.value=snapshotRows;factorRuns.value=factorRows
    datasets.value=datasetRows;experiments.value=experimentRows;models.value=modelRows
    backtests.value=backtestRows;jobs.value=jobRows;paperAccounts.value=accountRows
  }finally{loading.value=false}
}
onMounted(load)

const failureList=computed(()=>Object.entries(failures.value).map(([label,message])=>`${label}：${message}`))

function newest(items:any[]){
  return [...items].sort((left,right)=>new Date(right?.created_at||0).getTime()-new Date(left?.created_at||0).getTime())[0]||null
}
function relativeTime(value?:string|null){
  if(!value)return '还没有产物'
  const stamp=new Date(value).getTime()
  if(!Number.isFinite(stamp))return '时间未知'
  const minute=60000,hour=60*minute,day=24*hour,diff=Date.now()-stamp
  if(diff<minute)return '刚刚'
  if(diff<hour)return `${Math.floor(diff/minute)} 分钟前`
  if(diff<day)return `${Math.floor(diff/hour)} 小时前`
  if(diff<30*day)return `${Math.floor(diff/day)} 天前`
  return new Date(value).toLocaleDateString('zh-CN')
}
function greeting(){
  const hour=new Date().getHours()
  return hour<12?'上午好':hour<18?'下午好':'晚上好'
}

const userLabel=computed(()=>user.value?.display_name||'研究者')
const standardized=computed(()=>versions.value.filter(item=>item.layer==='standardized'&&item.status==='ready'))
const readySnapshots=computed(()=>snapshots.value.filter(item=>item.status==='ready'))
const succeededFactorRuns=computed(()=>factorRuns.value.filter(item=>item.status==='succeeded'))
const readyDatasets=computed(()=>datasets.value.filter(item=>item.status==='ready'))
const latestVersion=computed(()=>newest(standardized.value))
const latestSnapshot=computed(()=>newest(readySnapshots.value))
const latestFactorRun=computed(()=>newest(succeededFactorRuns.value))
const latestTraining=computed(()=>newest([...readyDatasets.value,...experiments.value,...models.value]))
const latestModel=computed(()=>newest(models.value))
const latestBacktest=computed(()=>newest(backtests.value))
const latestAccount=computed(()=>newest(paperAccounts.value))

// 五段的判断各自只调判断层，页面不写阈值。
const factorVerdict=computed<Verdict|null>(()=>{
  const run=latestFactorRun.value
  const factors=Object.values((run?.metrics?.factors||{}) as Record<string,any>)
  if(!run||!factors.length)return null
  const best=factors.reduce((left,right)=>Math.abs(Number(right.rank_ic_mean)||0)>Math.abs(Number(left.rank_ic_mean)||0)?right:left)
  const verdict=rankIcVerdict(Number(best.rank_ic_mean))
  const passed=(run.selected_feature_slugs||[]).length
  if(!passed)return{...verdict,label:`${factors.length} 个均无效`}
  // 已经通过多重检验的因子，级别至少是“有效”，弱只是区分度高低，不再报红。
  const level:VerdictLevel=verdict.level==='weak'||verdict.level==='bad'?'ok':verdict.level
  return{...verdict,level,label:`${passed} 个有效`}
})
const trainingVerdict=computed<Verdict|null>(()=>{
  const model=latestModel.value
  return model?rocAucVerdict(model.metrics?.roc_auc):null
})
// 回测账本里的 excess_return 是百分点（-3.81 表示 -3.81%），判断层要小数；
// 没有成交事件说明整段全现金，属于有效结论而不是跑输。
const backtestVerdict=computed<Verdict|null>(()=>{
  const metrics=latestBacktest.value?.metrics
  if(!metrics||metrics.excess_return===undefined||metrics.excess_return===null)return null
  const trades=metrics.turnover_events??metrics.total_trades
  return excessReturnVerdict(Number(metrics.excess_return)/100,trades===undefined?null:Number(trades))
})

const stageCards=computed<StageCard[]>(()=>{
  const version=latestVersion.value,snapshot=latestSnapshot.value,factorRun=latestFactorRun.value
  const training=latestTraining.value,backtest=latestBacktest.value,account=latestAccount.value
  const model=latestModel.value
  return [
    {key:'data',no:'①',label:'获取数据',icon:Download,ready:Boolean(version),
      to:version?`/data-center/versions/${version.id}`:'/data-center',
      title:version?(version.specification?.name||'标准化行情数据'):missingTitle(['数据版本'],'还没有研究数据'),
      note:version?`${version.row_count??'—'} 行 · 至 ${version.specification?.end_date||'—'}`:'先同步一份行情，后面每一步都用它',
      time:relativeTime(version?.created_at),verdict:null,status:version?.status??null},
    {key:'factor',no:'②',label:'因子',icon:Filter,ready:Boolean(factorRun),
      to:factorRun?'/factor-research':(snapshot?`/data-center/snapshots/${snapshot.id}`:'/data-center?focus=snapshots'),
      title:factorRun?.name||snapshot?.name||missingTitle(['因子快照','因子检验'],'还没有因子检验'),
      note:factorRun?'选股理由已经用历史数据检验过':(snapshot?`快照已就绪：${snapshot.row_count??'—'} 行`:'先在数据段把因子固化成快照'),
      time:relativeTime(factorRun?.created_at||snapshot?.created_at),verdict:factorVerdict.value,status:null},
    {key:'train',no:'③',label:'训练',icon:BrainCircuit,ready:Boolean(model),
      to:model?`/models/${model.id}`:(training?.to||(readyDatasets.value.length?'/experiments/new':'/datasets/new')),
      title:model?.name||training?.name||missingTitle(['训练数据','训练实验','模型'],'还没有训练模型'),
      note:model?`算法 ${algorithmLabel(model.algorithm)} · 阶段 ${statusLabel(model.stage)}`:'用通过检验的因子训练一个预测模型',
      time:relativeTime(model?.created_at||training?.created_at),verdict:trainingVerdict.value,status:null},
    {key:'backtest',no:'④',label:'回测',icon:FlaskConical,ready:Boolean(backtest),
      to:backtest?`/backtests/${backtest.id}`:'/backtests/new',
      title:backtest?backtestName(backtest):missingTitle(['回测'],'还没有回测记录'),
      note:backtest?`${backtest.start_date} → ${backtest.end_date}`:'用模型没见过的数据模拟真实买卖',
      time:relativeTime(backtest?.created_at),verdict:backtestVerdict.value,status:null},
    {key:'paper',no:'⑤',label:'模拟盘',icon:WalletCards,ready:Boolean(account),
      to:'/paper',
      title:account?.name||missingTitle(['模拟盘'],'还没有模拟盘账户'),
      note:account?'每个交易日收盘生成明天的交易计划':'绑定生产模型，纸上跟踪盈亏',
      time:account?relativeTime(account.created_at):'—',verdict:null,status:account?.status??null,statusLabel:account?undefined:'待配置'},
  ]
})

function backtestName(row:any){
  if(row.signal_source==='model_oos'||row.strategy_name==='model_probability')return '模型组合回测'
  return ({right_trend:'右侧趋势策略',v_shape:'V型反转策略'} as Record<string,string>)[row.strategy_name]||row.strategy_name||'策略回测'
}
// 控制台只说算法的人话短名（训练页保留各自的详细说明）。
const ALGORITHM_LABELS:Record<string,string>={
  hist_gradient_boosting:'梯度提升树',random_forest:'随机森林',extra_trees:'极端随机树',logistic_regression:'逻辑回归',
}
function algorithmLabel(value?:string|null){
  const key=String(value??'')
  return ALGORITHM_LABELS[key]||key||'未记录算法'
}

// 下一步只给一个动作：先补流水线第一个缺口；链路补齐后，如果信号本身偏弱，
// 优先回到因子页扩大截面复检，而不是继续在模型上调参。
const nextStep=computed(()=>{
  if(!latestVersion.value)return{title:'同步第一份行情数据',why:'项目里还没有通过质检的行情数据，因子、训练和回测都要用它。',action:'去获取数据',to:'/data-center',icon:Download}
  if(!latestSnapshot.value)return{title:'把因子固化成快照',why:'行情已就绪，但还没有因子快照；因子表是检验和训练的共同输入。',action:'去生成快照',to:'/data-center?focus=snapshots',icon:Sparkles}
  if(!latestFactorRun.value)return{title:'跑一次因子检验',why:'有快照但还没检验过因子，先确认哪些“选股理由”真的有效，再拿去训练。',action:'去检验因子',to:'/factor-research',icon:Filter}
  if(!readyDatasets.value.length)return{title:'构建训练数据',why:'因子已经检验过，把它们和未来涨跌对齐成一张训练表格。',action:'去建训练数据',to:'/datasets/new',icon:Database}
  if(!latestModel.value)return{title:'训练第一个模型',why:'训练数据已就绪，可以训练一个预测“谁会跑赢大盘”的模型。',action:'去训练',to:'/experiments/new',icon:BrainCircuit}
  if(!latestBacktest.value)return{title:'用模型跑一次组合回测',why:'模型已登记，用没见过的数据模拟真实买卖，看扣掉手续费后赚不赚钱。',action:'去回测',to:'/backtests/new',icon:FlaskConical}
  const verdict=trainingVerdict.value
  if(verdict&&(verdict.level==='weak'||verdict.level==='bad')){
    return{title:'先解决信号偏弱，再往下走',why:`最近模型的预测能力${verdict.label}（${verdict.hint}）。先回到因子页扩大股票截面复检，比继续调模型更划算。`,action:'去复检因子',to:'/factor-research',icon:Filter}
  }
  if(!latestAccount.value)return{title:'创建模拟盘账户',why:'研究链路已经跑通，把生产模型接到模拟盘，每天自动生成交易计划。',action:'去模拟盘',to:'/paper',icon:WalletCards}
  return{title:'跟踪模拟盘信号',why:'研究链路完整，接下来只需要每天复核模拟盘生成的交易计划。',action:'查看模拟盘',to:'/paper',icon:WalletCards}
})

// 最近动态优先用任务流水，任务表为空时退回研究产物，保证首页始终有事实可看。
const activity=computed<ActivityItem[]>(()=>{
  const jobRows:ActivityItem[]=jobs.value.slice(0,8).map(job=>({
    key:`job-${job.id}`,status:job.status,title:`${jobKindLabel(job.kind)}${job.status==='succeeded'?'完成':''}`,
    detail:jobDetail(job),time:relativeTime(job.created_at),
    to:jobTarget(job)?.to||'/jobs',toLabel:jobTarget(job)?.label,
  }))
  if(jobRows.length)return jobRows.slice(0,6)
  const products=[
    ...datasets.value.map(item=>({name:item.name,status:item.status,created_at:item.created_at,kind:'训练数据',to:'/datasets'})),
    ...experiments.value.map(item=>({name:item.name,status:item.status,created_at:item.created_at,kind:'训练实验',to:'/experiments'})),
    ...models.value.map(item=>({name:item.name,status:item.stage,created_at:item.created_at,kind:'模型',to:`/models/${item.id}`})),
    ...backtests.value.map(item=>({name:backtestName(item),status:null,created_at:item.created_at,kind:'回测报告',to:`/backtests/${item.id}`})),
  ].filter(item=>Boolean(item.created_at)).sort((left,right)=>new Date(right.created_at).getTime()-new Date(left.created_at).getTime())
  return products.slice(0,6).map((item,index)=>({
    key:`product-${index}`,status:item.status||'succeeded',title:`${item.kind} ${item.name}`,
    detail:'研究产物已登记',time:relativeTime(item.created_at),to:item.to,toLabel:'打开',
  }))
})
function jobDetail(job:any){
  const summary=job.result_summary||{}
  if(job.status==='failed')return job.error_message||'未记录失败原因'
  switch(job.kind){
    case 'data_sync':return summary.rows?`同步 ${summary.rows} 行行情`:'行情已入库'
    case 'feature_materialize':return summary.rows?`物化 ${summary.rows} 行 × ${(summary.features||[]).length} 个因子`:'因子表已生成'
    case 'factor_research':return `${summary.factor_count??0} 个因子参与检验，通过 ${(summary.selected||[]).length} 个`
    case 'dataset':return summary.rows?`生成 ${summary.rows} 行训练样本`:'训练表格已生成'
    case 'training':return summary.model_id?'模型已登记到模型仓库':'训练完成，等待登记模型'
    case 'sealed_evaluation':return '终检结果已生成（每个模型仅一次）'
    case 'backtest':return summary.excess_return!==undefined?`超额收益 ${Number(summary.excess_return).toFixed(2)} 个百分点`:'回测报告已生成'
    case 'prediction':return `${summary.rows??'—'} 行预测，打分区间 ${summary.score_start??'—'} → ${summary.score_end??'—'}`
    case 'paper_automation':return `生成 ${summary.proposed_orders??0} 笔待复核订单（${summary.signal_date??'—'}）`
    case 'drift_monitor':return `最大特征漂移 PSI ${summary.max_feature_psi??'—'}，告警级别 ${summary.alert_level??'—'}`
    default:{
      const section=jobSectionLabel(job.kind)
      return section==='其他'?'后台计算':`${section}链路`
    }
  }
}

const runningJobs=computed(()=>jobs.value.filter(job=>['queued','running','cancel_requested'].includes(job.status)))
const failedJobs=computed(()=>jobs.value.filter(job=>job.status==='failed'))

// 需要关注只放“现在要动手”的事：失败任务（带原因+重试）、数据陈旧、运行中任务、
// 模拟盘未配置。没有问题的项目看到的是“一切正常”。
const attention=computed<AttentionItem[]>(()=>{
  const items:AttentionItem[]=[]
  for(const job of failedJobs.value.slice(0,3)){
    items.push({key:`failed-${job.id}`,level:'bad',label:'失败',title:`${jobKindLabel(job.kind)}失败`,
      detail:job.error_message||'未记录失败原因',time:relativeTime(job.completed_at||job.created_at),retry:job.id})
  }
  const version=latestVersion.value
  const endDate=version?.specification?.end_date
  if(endDate){
    const days=Math.floor((Date.now()-new Date(`${endDate}T00:00:00`).getTime())/86400000)
    if(days>=3)items.push({key:'stale-data',level:'warn',label:'提示',title:`行情只更新到 ${endDate}`,
      detail:`距今 ${days} 天没有新数据，回测和预测都会停在旧区间。`,time:relativeTime(version.created_at),to:'/data-center',action:'去同步数据'})
  }
  for(const job of runningJobs.value.slice(0,3)){
    items.push({key:`running-${job.id}`,level:'na',label:'进行中',title:`${jobKindLabel(job.kind)}正在计算`,
      detail:`已完成 ${Math.round(Number(job.progress)||0)}%${job.worker_name?` · 计算节点 ${job.worker_name}`:''}`,
      time:relativeTime(job.started_at||job.created_at),to:'/jobs',action:'去任务中心'})
  }
  if(!paperAccounts.value.length)items.push({key:'paper-missing',level:'na',label:'待配置',title:'模拟盘还没有账户',
    detail:'绑定一个生产模型后，每个交易日收盘自动生成明天的交易计划。',time:'—',to:'/paper',action:'去创建'})
  return items
})

async function retry(jobId:string){
  retrying.value=jobId;actionError.value=''
  try{await api.post(`/jobs/${jobId}/retry`);await load()}
  catch(exception:any){actionError.value=`重试失败：${errorMessage(exception)}`}
  finally{retrying.value=''}
}
</script>

<template>
  <section>
    <div class="console-head">
      <div>
        <h2>{{greeting()}}，{{userLabel}}</h2>
        <p>这是你的研究控制台。流水线状态一目了然，只看需要关注的。</p>
      </div>
      <button class="secondary" :disabled="loading" @click="load"><RefreshCw :size="15" :class="{spin:loading}"/>刷新</button>
    </div>

    <p v-if="failureList.length" class="error-box">部分数据加载失败（其余区块按已返回的数据展示，结果可能不完整）：{{failureList.join('；')}}</p>
    <p v-if="actionError" class="error-box">{{actionError}}</p>

    <nav class="stages" aria-label="五段研究流水线状态">
      <RouterLink v-for="card in stageCards" :key="card.key" class="stage" :class="{missing:!card.ready}" :to="card.to" :title="card.note">
        <div class="stage-head"><span class="stage-no">{{card.no}}</span><span class="stage-label">{{card.label}}</span></div>
        <b>{{card.title}}</b>
        <p>{{card.note}}</p>
        <div class="stage-foot">
          <VerdictBadge v-if="card.verdict" :verdict="card.verdict"/>
          <StatusBadge v-else-if="card.status!==null||card.statusLabel" :status="card.status" :label="card.statusLabel"/>
          <small>{{card.time}}</small>
        </div>
      </RouterLink>
    </nav>

    <article class="next-step">
      <span class="next-icon"><component :is="nextStep.icon" :size="22"/></span>
      <div class="next-copy">
        <small>下一步建议</small>
        <b>{{nextStep.title}}</b>
        <p>{{nextStep.why}}</p>
      </div>
      <RouterLink class="next-action" :to="nextStep.to">{{nextStep.action}}<ArrowRight :size="15"/></RouterLink>
    </article>

    <div class="console-grid">
      <article class="panel">
        <div class="panel-head"><div><h3>最近动态</h3><p>后台计算和刚落地的研究产物</p></div><RouterLink to="/jobs">全部任务</RouterLink></div>
        <div class="timeline">
          <RouterLink v-for="item in activity" :key="item.key" class="timeline-row" :to="item.to">
            <StatusBadge :status="item.status"/>
            <div><b>{{item.title}}</b><small>{{item.detail}}</small></div>
            <span v-if="item.toLabel" class="timeline-link">{{item.toLabel}}<ArrowRight :size="13"/></span>
            <time>{{item.time}}</time>
          </RouterLink>
          <div v-if="!activity.length&&!loading" class="empty">暂无研究动态。同步数据、检验因子或训练模型后，这里会按时间列出每一次计算。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h3>需要关注</h3><p>失败、陈旧数据和其他要动手的事</p></div><RotateCcw :size="17"/></div>
        <div class="timeline">
          <div v-for="item in attention" :key="item.key" class="timeline-row">
            <StatusBadge :status="item.level==='bad'?'failed':item.level==='warn'?'pending':''" :label="item.label"/>
            <div><b>{{item.title}}</b><small>{{item.detail}}</small></div>
            <button v-if="item.retry" class="text-button" :disabled="retrying===item.retry" @click="retry(item.retry!)"><RotateCcw :size="13"/>重试</button>
            <RouterLink v-else-if="item.to" class="timeline-link" :to="item.to">{{item.action}}<ArrowRight :size="13"/></RouterLink>
            <time>{{item.time}}</time>
          </div>
          <div v-if="!attention.length&&!loading" class="empty">没有需要处理的问题：任务全部正常，数据也是新的。</div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.console-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}
.console-head h2{margin:0;font:700 21px Manrope;color:#1a2233}
.console-head p{margin:5px 0 0;color:#5b6474;font-size:13px}
.stages{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
.stage{display:grid;gap:6px;padding:14px 16px;border:1px solid #e7e9ee;border-radius:12px;background:#fff;box-shadow:0 1px 3px #1018280f;color:inherit;text-decoration:none;transition:border-color .16s ease,transform .16s ease}
.stage:hover{border-color:#c7cbe0;transform:translateY(-1px)}
.stage.missing{border-style:dashed;box-shadow:none}
.stage-head{display:flex;align-items:center;gap:6px;color:#98a0ae;font-size:12px}
.stage-no{color:#4f46e5;font-weight:700}
.stage-label{color:#5b6474;font-weight:600}
.stage b{color:#1a2233;font-size:13px;line-height:1.5;overflow-wrap:anywhere}
.stage.missing b{color:#8b97a7;font-weight:600}
.stage>p{margin:0;color:#98a0ae;font-size:11px;line-height:1.5;overflow-wrap:anywhere}
.stage-foot{display:flex;align-items:center;gap:8px;margin-top:2px}
.stage-foot small{color:#98a0ae;font-size:10px}
.next-step{display:flex;align-items:center;gap:16px;margin:18px 0;padding:20px 24px;border-radius:14px;background:linear-gradient(135deg,#4f46e5,#6d5ef0);color:#fff;box-shadow:0 12px 30px #4f46e529}
.next-icon{width:44px;height:44px;flex:none;display:grid;place-items:center;border-radius:12px;background:#ffffff26}
.next-copy{min-width:0;flex:1}
.next-copy small{display:block;color:#ffffffb8;font-size:10px;font-weight:700;letter-spacing:1.1px}
.next-copy b{display:block;margin:5px 0 4px;font-size:16px}
.next-copy p{margin:0;color:#ffffffd9;font-size:13px;line-height:1.65}
.next-action{flex:none;display:flex;align-items:center;gap:6px;padding:9px 18px;border-radius:10px;background:#fff;color:#4f46e5;font-size:13px;font-weight:600;text-decoration:none}
.next-action:hover{background:#f2f1ff}
.console-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.timeline{margin-top:6px}
.timeline-row{display:flex;align-items:center;gap:12px;padding:12px 2px;border-top:1px solid #f0f1f5;font-size:13px;color:inherit;text-decoration:none}
.timeline-row:hover{background:#fafafd}
.timeline-row:first-child{border-top:none}
.timeline-row>div{min-width:0;flex:1}
.timeline-row b,.timeline-row small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.timeline-row b{color:#1a2233;font-size:13px;font-weight:600}
.timeline-row small{margin-top:3px;color:#98a0ae;font-size:11px}
.timeline-row time{margin-left:auto;flex:none;color:#98a0ae;font-size:11px}
.timeline-link{flex:none;display:flex;align-items:center;gap:4px;color:#4f46e5;font-size:11px;text-decoration:none}
@media(max-width:1100px){.stages{grid-template-columns:repeat(3,minmax(0,1fr))}.console-grid{grid-template-columns:1fr}}
@media(max-width:720px){.stages{grid-template-columns:repeat(2,minmax(0,1fr))}.next-step{align-items:flex-start;flex-wrap:wrap}.next-action{margin-left:60px}.timeline-row{flex-wrap:wrap}.timeline-row time{margin-left:0}}
</style>
