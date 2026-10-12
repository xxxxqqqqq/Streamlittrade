<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {pollJobUntilTerminal} from '../jobPolling'
import {user} from '../auth'
import StatusBadge from '../components/StatusBadge.vue'
import MetricValue from '../components/MetricValue.vue'
import SectionTabs from '../components/SectionTabs.vue'
import GuideCard from '../components/GuideCard.vue'
import VerdictBadge from '../components/VerdictBadge.vue'
import {type Verdict,icDecayVerdict,rankIcVerdict,rocAucVerdict} from '../verdict'
import {labelModeLabel,selectionMetricLabel} from '../labels'
import {trainingTabs} from '../sections'
import {ArrowLeft,Boxes,CalendarDays,Database,GitBranch,Grid3x3,RotateCcw,ShieldCheck,Sparkles} from 'lucide-vue-next'

const route=useRoute(),router=useRouter(),model=ref<any>(null),sealed=ref<any>(null),loading=ref(true),error=ref('')
const reason=ref('已检查样本外指标、时间隔离和经济指标'),changing=ref(false)
const sealedProtocol=ref({top_n:5,minimum_probability:0.55,rebalance_frequency:5,initial_cash:1000000,max_volume_participation:0.05,lot_size:100,commission:0.0003,minimum_commission:5,stamp_duty:0.0005,slippage:0.001})
onMounted(async()=>{
  try{
    model.value=(await api.get(`/models/${route.params.id}/detail`)).data
    if(model.value)sealed.value=(await api.get(`/models/${model.value.id}/sealed-evaluation`)).data
    if(!model.value)error.value='没有找到该模型版本'
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{loading.value=false}
})
const metrics=computed(()=>model.value?.metrics||{})
const reproducibility=computed(()=>model.value?.reproducibility||{})
const importance=computed(()=>metrics.value.feature_importance||[])
const calibration=computed(()=>metrics.value.calibration||{})
// "这次训练在学什么"：因子数、预测周期、学习区间和模型没见过的打分区间。
const researchSplit=computed(()=>metrics.value.research_split||{})
const featureCount=computed(()=>reproducibility.value.features?.length||importance.value.length||0)
const horizon=computed(()=>reproducibility.value.dataset?.horizon??null)
const datasetName=computed(()=>reproducibility.value.dataset?.name||'训练数据')
// 标签口径：这次训练学的是哪种"答案"。旧数据集没记 label_mode 就不显示。
const labelMode=computed(()=>labelModeLabel(reproducibility.value.label_mode||reproducibility.value.dataset?.label_mode))
// 网格搜索留档：只有真的跑过网格的模型才有 grid_search，其他模型不出现这张卡。
const gridSearch=computed<any>(()=>{
  const value=reproducibility.value.grid_search,candidates=Array.isArray(value?.candidates)?value.candidates:[]
  return candidates.length&&candidates[0]?.parameters?value:null
})
// 候选表只列网格扫过的维度（learning_rate / max_leaf_nodes）；旧记录没有 grid
// 声明时退化成"逐候选比较参数差异"。
const gridKeys=computed<string[]>(()=>{
  const declared=Object.keys(gridSearch.value?.grid||{})
  if(declared.length)return declared
  const candidates=gridSearch.value?.candidates||[],base=candidates[0]?.parameters||{}
  return Object.keys(base).filter(key=>candidates.some((item:any)=>String(item.parameters?.[key])!==String(base[key])))
})
const gridFolds=computed<any[]>(()=>gridSearch.value?.selection_folds||[])
const gridFoldCount=computed(()=>gridFolds.value.length||gridSearch.value?.candidates?.[0]?.fold_rank_ics?.length||0)
// 选中行：先按参数完全一致匹配后端登记的选中参数，匹配不到再退化成均值最高的一组。
const gridSelectedIndex=computed(()=>{
  const candidates=gridSearch.value?.candidates||[],target=JSON.stringify(gridSearch.value?.selected?.parameters)
  const matched=candidates.findIndex((item:any)=>JSON.stringify(item.parameters)===target)
  if(matched>=0)return matched
  return candidates.reduce((best:number,item:any,index:number)=>typeof item.rank_ic==='number'&&(best<0||item.rank_ic>Number(candidates[best].rank_ic))?index:best,-1)
})
const gridColumns=computed(()=>{
  const folds=gridFoldCount.value?` repeat(${gridFoldCount.value},84px)`:''
  return `repeat(${Math.max(gridKeys.value.length,1)},minmax(0,1fr))${folds} 96px 104px`
})
const gridSelectionNote=computed(()=>`按${selectionMetricLabel(gridSearch.value?.selection_metric)||'全部调参折的 OOS RankIC 均值'}选优`)
function foldTitle(index:number){
  const fold=gridFolds.value[index]
  return fold?`第 ${fold.fold} 折 · ${range(fold.test_start,fold.test_end)}`:`第 ${index+1} 折`
}
function range(start?:string,end?:string){return start&&end?`${start} ~ ${end}`:'—'}
interface MetricCard{label:string;value:number|null|undefined;mode?:'rate'|'ratio';digits?:number;tone?:boolean;verdict?:Verdict|null}
const metricCards=computed<MetricCard[]>(()=>[
  {label:'预测能力（ROC AUC）',value:metrics.value.roc_auc,verdict:rocAucVerdict(metrics.value.roc_auc)},
  {label:'选股区分度（Rank IC）',value:metrics.value.rank_ic,mode:'ratio',digits:3,verdict:rankIcVerdict(metrics.value.rank_ic)},
  {label:'信号衰减',value:metrics.value.rank_ic_decay,mode:'ratio',digits:3,verdict:icDecayVerdict(metrics.value.rank_ic_decay)},
  {label:'成本后收益（研究口径估算）',value:metrics.value.cost_adjusted_return,tone:true},
  {label:'超额收益（研究口径估算）',value:metrics.value.excess_return,tone:true},
  {label:'年化夏普',value:metrics.value.annualized_sharpe,mode:'ratio',digits:3},
])
async function changeStage(stage:string){
  changing.value=true;error.value=''
  try{model.value=(await api.patch(`/models/${model.value.id}/stage`,{stage,reason:reason.value})).data}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{changing.value=false}
}
async function rollback(){
  changing.value=true;error.value=''
  try{model.value=(await api.post(`/models/${model.value.id}/rollback`,{reason:reason.value})).data}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{changing.value=false}
}
async function openSealed(){
  changing.value=true;error.value=''
  try{
    const response=await api.post(`/models/${model.value.id}/sealed-evaluation`,{reason:reason.value,portfolio_protocol:sealedProtocol.value})
    const job=await pollJobUntilTerminal(async()=>(await api.get(`/jobs/${response.data.job_id}`)).data)
    if(job.status!=='succeeded')throw new Error(job.error_message||'终检评估未完成')
    sealed.value=(await api.get(`/models/${model.value.id}/sealed-evaluation`)).data
    model.value=(await api.get(`/models/${route.params.id}/detail`)).data
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{changing.value=false}
}
</script>

<template>
  <section class="workflow">
    <SectionTabs :tabs="trainingTabs" label="训练段页签"/>
    <GuideCard
      :icon="Boxes"
      title="这一步在干什么"
      text="这是训练产出的模型：先看它学得怎么样（预测能力、区分度、衰减），再决定要不要回测和上线。"
    />
    <div class="crumb"><button @click="router.push('/models')"><ArrowLeft :size="15"/>返回模型仓库</button><span>研究流程 · 第 3/3 步</span></div>
    <div v-if="loading" class="panel empty">正在读取模型结果…</div>
    <div v-else-if="error&&!model" class="panel error-box">{{error}}</div>
    <template v-else>
      <article class="model-hero"><div class="feature-icon purple-bg"><Boxes :size="25"/></div><div><span class="eyebrow dark">REGISTERED MODEL</span><h2>{{model.name}}</h2><p>{{model.algorithm}} · Version {{model.version}}</p></div><div class="row-actions"><button v-if="model.prediction_artifact_uri" class="primary" @click="router.push(`/models/${model.id}/trade-workbench`)">模型交易工作台</button><button v-if="model.prediction_artifact_uri" class="secondary" @click="router.push({path:'/backtests/new',query:{model_id:model.id,prediction_scope:'tuning_oos'}})">验证区回测（可反复比较）</button><button v-if="sealed?.status==='succeeded'" class="secondary" @click="router.push({path:'/backtests/new',query:{model_id:model.id,prediction_scope:'sealed_oos'}})">终检回测（一次性）</button></div><StatusBadge :status="model.stage"/></article>
      <div class="learning-brief">
        <b>这次训练在学什么</b>
        <p>用 <b>{{featureCount}} 个因子</b>学习预测 <b>{{horizon??'—'}} 个交易日后的涨跌</b>，训练数据是 {{datasetName}}。</p>
        <div class="brief-ranges">
          <span>学习区间（旧数据）：<b>{{range(researchSplit.training?.start,researchSplit.training?.end)}}</b></span>
          <span>打分区间（模型没见过）：<b>{{range(researchSplit.tuning?.start,researchSplit.tuning?.end)}}</b></span>
          <span>{{sealed?.status==='succeeded'?'终检已完成（每个模型只能做一次）':'终检区间仍锁定（一次性，未使用）'}}</span>
          <span v-if="labelMode">{{labelMode}}</span>
        </div>
      </div>
      <div class="result-grid"><article class="panel metric-result" v-for="card in metricCards" :key="card.label"><small>{{card.label}}</small><MetricValue :value="card.value" :mode="card.mode" :digits="card.digits" :tone="card.tone"/><VerdictBadge v-if="card.verdict" :verdict="card.verdict"/></article></div>
      <article v-if="calibration.bins" class="panel"><div class="panel-head"><div><h3>概率校准与可靠性</h3><p>验证区样本外概率；Brier / Log Loss 越低越好，ECE 衡量预测概率与实际频率的偏差。</p></div><ShieldCheck :size="18"/></div><div class="config-strip"><span>校准后 Brier {{calibration.brier_score}}</span><span>原始 Brier {{calibration.raw_brier_score}}</span><span>校准后 Log Loss {{calibration.log_loss}}</span><span>ECE {{calibration.expected_calibration_error}}</span></div><div class="artifact" v-for="bin in calibration.bins" :key="bin.lower"><code>{{Math.round(bin.lower*100)}}%–{{Math.round(bin.upper*100)}}% · 预测 <MetricValue :value="bin.mean_probability"/> · 实际 <MetricValue :value="bin.observed_frequency"/> · n={{bin.count}}</code></div></article>
      <article v-if="metrics.evaluation_scope==='tuning_oos'" class="panel"><div class="panel-head"><div><h3>三段式研究边界</h3><p>训练区和验证区的结果可以反复比较；终检只能交给一个锁定的模型，做完就不能再改。</p></div><ShieldCheck :size="18"/></div><div class="config-strip"><span>训练区 {{metrics.research_split?.training?.start}} → {{metrics.research_split?.training?.end}}</span><span>验证区 {{metrics.research_split?.tuning?.start}} → {{metrics.research_split?.tuning?.end}}</span><span>终检区 {{metrics.research_split?.sealed?.start}} → {{metrics.research_split?.sealed?.end}}</span><span>🔒 终检{{sealed?.status==='succeeded'?'已完成':'（每个模型只能做一次，结果不可改）'}}</span></div><template v-if="!sealed&&user?.role==='admin'"><p>开始终检前必须先把选股规则登记好；登记后参数与日期永久锁定，避免看到最终结果再回头调参。</p><div class="config-strip"><label>Top-N <input v-model.number="sealedProtocol.top_n" type="number" min="1" max="100"/></label><label>最低概率 <input v-model.number="sealedProtocol.minimum_probability" type="number" min="0" max="1" step="0.01"/></label><label>调仓日 <input v-model.number="sealedProtocol.rebalance_frequency" type="number" min="1" max="60"/></label><label>初始资金 <input v-model.number="sealedProtocol.initial_cash" type="number" min="1000"/></label></div><button class="primary" :disabled="changing" @click="openSealed"><ShieldCheck :size="15"/>🔒 锁定模型与规则，做唯一一次终检</button></template><div v-if="sealed?.metrics" class="result-grid"><article class="metric"><small>终检 ROC AUC</small><MetricValue :value="sealed.metrics.roc_auc"/></article><article class="metric"><small>终检 Rank IC</small><MetricValue :value="sealed.metrics.rank_ic" mode="ratio" :digits="3"/></article><article class="metric"><small>终检超额收益</small><MetricValue :value="sealed.metrics.excess_return" tone/></article></div><p v-if="sealed?.metrics">组合规则：{{JSON.stringify(sealed.metrics.portfolio_protocol||sealedProtocol)}} · {{sealed.metrics.portfolio_protocol_source==='preregistered'?'终检前已登记':'历史记录：使用系统默认规则，未在终检前登记'}}</p></article>
      <article v-if="sealed?.metrics?.calibration" class="panel"><div class="panel-head"><div><h3>终检概率门禁</h3><p>该结果只生成一次，用于确认概率可靠性没有在真正未见数据上失效。</p></div></div><div class="config-strip"><span>Brier {{sealed.metrics.calibration.brier_score}}</span><span>Raw Brier {{sealed.metrics.calibration.raw_brier_score}}</span><span>Log Loss {{sealed.metrics.calibration.log_loss}}</span><span>ECE {{sealed.metrics.calibration.expected_calibration_error}}</span></div></article>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>{{metrics.evaluation_scope==='tuning_oos'?'验证区结果':'可信训练验证'}}</h3><p>{{metrics.evaluation_scope==='tuning_oos'?'终检区从未参与的时间序列样本外结果':'时间线样本外结果'}}</p></div></div><dl class="detail-list"><div><dt><GitBranch :size="15"/>切分方式</dt><dd>{{metrics.split}}</dd></div><div><dt><Database :size="15"/>验证区样本</dt><dd>{{metrics.test_rows}}</dd></div><div><dt><CalendarDays :size="15"/>Purge / Embargo</dt><dd>{{metrics.purge_days}} / {{metrics.embargo_days}} 交易日</dd></div><div><dt><ShieldCheck :size="15"/>验证折数</dt><dd>{{metrics.folds?.length||0}}</dd></div></dl></article>
        <article class="panel"><div class="panel-head"><div><h3>可复现实验快照</h3><p>定位训练数据、运行环境和模型文件</p></div></div><dl class="detail-list"><div><dt>数据 SHA256</dt><dd><code>{{reproducibility.dataset?.content_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>模型 SHA256</dt><dd><code>{{reproducibility.model_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>样本外预测 SHA256</dt><dd><code>{{reproducibility.prediction_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>Python / sklearn</dt><dd>{{reproducibility.python_version}} / {{reproducibility.sklearn_version}}</dd></div><div><dt>随机种子</dt><dd>{{reproducibility.random_seed}}</dd></div></dl></article>
      </div>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>特征重要性</h3><p>验证区最后一折上的特征重要性（permutation importance）</p></div><Sparkles :size="18"/></div><div class="artifact" v-for="item in importance" :key="item.feature"><code>{{item.feature}} · {{Number(item.importance_mean).toFixed(6)}} ± {{Number(item.importance_std).toFixed(6)}}</code></div><div v-if="!importance.length" class="empty">该旧模型没有保存解释结果。</div></article>
        <article class="panel"><div class="panel-head"><div><h3>批量推理</h3><p>使用任意兼容特征快照生成可审计 Parquet</p></div></div><button class="primary" @click="router.push({path:'/predictions',query:{model_id:model.id}})"><Sparkles :size="15"/>创建预测任务</button></article>
      </div>
      <article class="panel"><div class="panel-head"><div><h3>验证区各折样本外结果</h3><p>只用于选参数，不能代表终检结果</p></div></div><div class="artifact" v-for="fold in metrics.folds||[]" :key="fold.fold"><code>Fold {{fold.fold}} · {{fold.test_start}} → {{fold.test_end}} · AUC {{fold.roc_auc}} · Balanced Acc {{fold.balanced_accuracy}}</code></div></article>
      <article v-if="gridSearch" class="panel grid-search-panel">
        <div class="panel-head"><div><h3>网格搜索（超参数是怎么选的）</h3><p>{{gridSelectionNote}}；高亮的一行就是最终拿去训练的这组参数。</p></div><Grid3x3 :size="18"/></div>
        <div class="config-strip">
          <span v-for="(value,key) in gridSearch.selected?.parameters" :key="key">{{key}} = {{value}}</span>
          <span>共比较 {{gridSearch.candidates.length}} 组参数 · {{gridFoldCount}} 折调参</span>
        </div>
        <div class="grid-search-table">
          <div class="grid-search-row head" :style="{gridTemplateColumns:gridColumns}">
            <span v-for="key in gridKeys" :key="key">{{key}}</span>
            <span v-for="index in gridFoldCount" :key="index" :title="foldTitle(index-1)">第 {{index}} 折</span>
            <span>各折均值</span><span>判断</span>
          </div>
          <div v-for="(candidate,index) in gridSearch.candidates" :key="index" class="grid-search-row" :class="{selected:index===gridSelectedIndex}" :style="{gridTemplateColumns:gridColumns}">
            <span v-for="key in gridKeys" :key="key">{{candidate.parameters?.[key]}}</span>
            <span v-for="(value,fold) in candidate.fold_rank_ics" :key="fold">{{typeof value==='number'?value.toFixed(4):'—'}}</span>
            <b><MetricValue :value="candidate.rank_ic" mode="ratio" :digits="4"/></b>
            <span class="grid-search-verdict"><VerdictBadge :verdict="rankIcVerdict(candidate.rank_ic)"/><i v-if="index===gridSelectedIndex" class="pick">已选</i></span>
          </div>
        </div>
        <p class="grid-search-note">每一折的 Rank IC 都是该折样本外的区分度；选参只在验证区调参折上比较，终检区始终没有参与。</p>
      </article>
      <p v-if="error" class="error-box">{{error}}</p>
      <article v-if="user?.role==='admin'" class="panel lifecycle"><div><h3>模型生命周期审批</h3><p>升级、归档与回滚操作都会写入审计日志。</p></div><input v-model="reason" minlength="3"/><div class="row-actions"><button v-if="model.stage==='candidate'" class="primary" :disabled="changing" @click="changeStage('validated')">通过验证</button><button v-if="model.stage==='validated'" class="primary" :disabled="changing" @click="changeStage('production')">发布生产</button><button v-if="model.stage==='archived'" class="primary" :disabled="changing" @click="rollback"><RotateCcw :size="15"/>回滚为生产</button><button v-if="model.stage!=='archived'" class="secondary" :disabled="changing" @click="changeStage('archived')">归档</button></div></article>
    </template>
  </section>
</template>

<style scoped>
.learning-brief{margin:0 0 16px;padding:16px 18px;border:1px solid #e3e1fb;border-radius:13px;background:linear-gradient(135deg,#f7f7ff,#fbfaff)}
.learning-brief>b{color:#4f46e5;font-size:13px}
.learning-brief p{margin:7px 0 0;color:#4b5a70;font-size:12.5px;line-height:1.7}
.learning-brief p>b{color:#1f2b3d}
.brief-ranges{display:flex;flex-wrap:wrap;gap:16px;margin-top:8px;color:#718096;font-size:11px}
.brief-ranges b{color:#33455c}
.metric-result .verdict-badge{margin-top:7px}
.grid-search-panel{margin-top:15px}
.grid-search-panel .panel-head>svg{color:#3978c8}
.grid-search-table{overflow-x:auto;border:1px solid #e2e8ef;border-radius:10px}
.grid-search-row{display:grid;align-items:center;min-width:640px;padding:9px 12px;border-top:1px solid #edf0f4;color:#526075;font-size:10px;font-variant-numeric:tabular-nums}
.grid-search-row:first-child{border-top:0}
.grid-search-row.head{background:#f6f8fb;color:#8793a3;font-size:9px;font-weight:700}
.grid-search-row.selected{background:#f2f7ff;box-shadow:inset 3px 0 0 #1768d7}
.grid-search-row.selected span,.grid-search-row.selected b{color:#1f3b63}
.grid-search-verdict{display:flex;align-items:center;gap:6px}
.grid-search-verdict .pick{padding:2px 6px;border-radius:99px;background:#e4f8f1;color:#0f7a58;font-size:9px;font-style:normal;font-weight:700;white-space:nowrap}
.grid-search-note{margin:10px 0 0;color:#8b97a7;font-size:10px;line-height:1.6}
@media(max-width:720px){.brief-ranges{flex-direction:column;gap:6px}}
</style>
