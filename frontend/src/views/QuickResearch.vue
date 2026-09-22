<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api'
import {CheckCircle2,ChevronDown,LoaderCircle,XCircle,Zap} from 'lucide-vue-next'

const router=useRouter()
const STEP_LABELS:Record<string,string>={
  materialize:'特征快照',factor_research:'因子研究',dataset:'研究数据集',
  training:'模型训练',backtest:'调参区回测',done:'完成',
}
const STEP_ORDER=['materialize','factor_research','dataset','training','backtest']

const versions=ref<any[]>([]),snapshots=ref<any[]>([]),pipelines=ref<any[]>([])
const error=ref(''),submitting=ref(false),active=ref<any>(null)
const showAdvanced=ref(false)
const form=ref({
  name:'一键研究',
  source:'version' as 'version'|'snapshot',
  data_version_id:'',feature_snapshot_id:'',
  algorithm:'hist_gradient_boosting',
  horizon:20,top_n:5,minimum_probability:0.55,rebalance_frequency:5,initial_cash:1000000,
})
const readyVersions=computed(()=>versions.value.filter(v=>v.layer==='standardized'&&v.status==='ready'))
const readySnapshots=computed(()=>snapshots.value.filter(s=>s.status==='ready'))
let timer:ReturnType<typeof setInterval>|null=null

function stopPolling(){if(timer){clearInterval(timer);timer=null}}
async function refreshActive(){
  if(!active.value)return
  active.value=(await api.get(`/pipelines/${active.value.id}`)).data
  if(active.value.status!=='running'){stopPolling();loadPipelines()}
}
async function loadPipelines(){pipelines.value=(await api.get('/pipelines')).data}

onMounted(async()=>{
  const [versionList,snapshotList]=await Promise.all([
    api.get('/versions'),api.get('/materializations'),
  ])
  versions.value=versionList.data;snapshots.value=snapshotList.data
  if(readyVersions.value.length)form.value.data_version_id=readyVersions.value[0].id
  if(readySnapshots.value.length)form.value.feature_snapshot_id=readySnapshots.value[0].id
  await loadPipelines()
})
onBeforeUnmount(stopPolling)

async function submit(){
  error.value='';submitting.value=true
  try{
    const payload:Record<string,any>={
      name:form.value.name,algorithm:form.value.algorithm,
      horizon:Number(form.value.horizon),top_n:Number(form.value.top_n),
      minimum_probability:Number(form.value.minimum_probability),
      rebalance_frequency:Number(form.value.rebalance_frequency),
      initial_cash:Number(form.value.initial_cash),
    }
    if(form.value.source==='version')payload.data_version_id=form.value.data_version_id
    else payload.feature_snapshot_id=form.value.feature_snapshot_id
    const response=await api.post('/pipelines/quick-research',payload)
    active.value=(await api.get(`/pipelines/${response.data.pipeline_id}`)).data
    stopPolling();timer=setInterval(refreshActive,3000)
    await loadPipelines()
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message||'提交失败'}
  finally{submitting.value=false}
}

function openPipeline(item:any){active.value=item;stopPolling();if(item.status==='running')timer=setInterval(refreshActive,3000)}
function stepState(pipeline:any,step:string){return pipeline?.spec?.steps?.[step]?.status||'pending'}
function resultLink(pipeline:any):string{
  const backtest=pipeline?.spec?.steps?.backtest?.resource_id
  if(pipeline?.status==='succeeded'&&backtest)return `/backtests/${backtest}`
  const training=pipeline?.spec?.steps?.training?.resource_id
  return training?`/experiments`:'/jobs'
}
</script>

<template>
  <section class="workflow">
    <article class="panel form-card">
      <div class="form-heading"><div class="feature-icon purple-bg"><Zap :size="23"/></div><div><h2>一键研究</h2><p>一次提交，服务端自动按序完成 特征快照 → 因子研究 → 数据集 → 训练 → 调参区回测。所有步骤沿用正式的不可变资产与门禁，可在任务中心随时查看。</p></div></div>
      <form @submit.prevent="submit">
        <div class="field full"><label>研究名称</label><input v-model="form.name" required minlength="2"/></div>
        <div class="form-grid">
          <div class="field"><label>数据来源</label><select v-model="form.source"><option value="version">标准化数据版本（从快照做起）</option><option value="snapshot">已有特征快照（跳过第 1 步）</option></select></div>
          <div class="field" v-if="form.source==='version'"><label>标准化数据版本</label><select v-model="form.data_version_id" required><option disabled value="">请选择</option><option v-for="item in readyVersions" :key="item.id" :value="item.id">{{item.id.slice(0,8)}} · {{item.row_count}} 行 · {{String(item.created_at).slice(0,10)}}</option></select></div>
          <div class="field" v-else><label>已就绪特征快照</label><select v-model="form.feature_snapshot_id" required><option disabled value="">请选择</option><option v-for="item in readySnapshots" :key="item.id" :value="item.id">{{item.name}} · {{item.row_count}} 行</option></select></div>
          <div class="field"><label>算法</label><select v-model="form.algorithm"><option value="hist_gradient_boosting">Histogram Gradient Boosting</option><option value="extra_trees">Extra Trees</option><option value="random_forest">Random Forest</option><option value="logistic_regression">Logistic Regression</option></select></div>
          <div class="field"><label>预测周期（交易日）</label><input v-model.number="form.horizon" type="number" min="1" max="60"/></div>
        </div>
        <button type="button" class="text-button advanced-toggle" @click="showAdvanced=!showAdvanced">组合规则（推荐默认值）<ChevronDown :size="14" :class="{open:showAdvanced}"/></button>
        <div v-if="showAdvanced" class="form-grid">
          <div class="field"><label>Top-N 持仓</label><input v-model.number="form.top_n" type="number" min="1" max="100"/></div>
          <div class="field"><label>最低入选概率</label><input v-model.number="form.minimum_probability" type="number" min="0" max="1" step="0.01"/></div>
          <div class="field"><label>调仓频率（交易日）</label><input v-model.number="form.rebalance_frequency" type="number" min="1" max="60"/></div>
          <div class="field"><label>初始资金</label><input v-model.number="form.initial_cash" type="number" min="1"/></div>
        </div>
        <p v-if="error" class="error-box">{{error}}</p>
        <div class="form-actions"><button class="primary" :disabled="submitting"><LoaderCircle v-if="submitting" :size="16" class="spin"/><Zap v-else :size="16"/>{{submitting?'正在提交':'使用推荐配置一键研究'}}</button></div>
      </form>
    </article>

    <article v-if="active" class="panel form-card">
      <div class="form-heading"><div class="feature-icon" :class="active.status==='succeeded'?'green-bg':active.status==='failed'?'red-bg':'purple-bg'"><LoaderCircle v-if="active.status==='running'" :size="22" class="spin"/><CheckCircle2 v-else-if="active.status==='succeeded'" :size="22"/><XCircle v-else :size="22"/></div><div><h2>{{active.name}}</h2><p>当前步骤：{{STEP_LABELS[active.current_step]||active.current_step}}<template v-if="active.error_message"> · {{active.error_message}}</template></p></div></div>
      <div class="stepper">
        <div v-for="step in STEP_ORDER" :key="step" :class="{done:['succeeded','skipped'].includes(stepState(active,step)),active:active.current_step===step&&active.status==='running'}">
          <i>{{['succeeded','skipped'].includes(stepState(active,step))?'✓':STEP_ORDER.indexOf(step)+1}}</i><span>{{STEP_LABELS[step]}}</span>
        </div>
      </div>
      <div v-if="active.status==='succeeded'" class="form-actions"><button class="primary" @click="router.push(resultLink(active))">查看调参区回测报告</button></div>
      <div v-else class="background-task-note">流水线在服务端运行，关闭本页不影响执行；也可以前往 <button type="button" class="text-button" @click="router.push('/jobs')">任务中心</button> 查看每个步骤的任务详情。</div>
    </article>

    <article v-if="pipelines.length" class="panel form-card">
      <h2>历史流水线</h2>
      <div class="pipeline-list">
        <button v-for="item in pipelines" :key="item.id" class="pipeline-row" @click="openPipeline(item)">
          <i :class="item.status"/><b>{{item.name}}</b><span>{{STEP_LABELS[item.current_step]||item.current_step}}</span><small>{{String(item.created_at).slice(0,16).replace('T',' ')}}</small>
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.advanced-toggle{display:inline-flex;align-items:center;gap:4px;margin:4px 0 10px}
.advanced-toggle svg.open{transform:rotate(180deg)}
.pipeline-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.pipeline-row{display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--border,#e5e7eb);border-radius:10px;background:none;cursor:pointer;text-align:left}
.pipeline-row:hover{background:var(--surface-hover,#f9fafb)}
.pipeline-row i{width:9px;height:9px;border-radius:50%;background:#9ca3af}
.pipeline-row i.running{background:#8b5cf6;animation:pulse 1.2s infinite}
.pipeline-row i.succeeded{background:#16a34a}
.pipeline-row i.failed,.pipeline-row i.canceled{background:#dc2626}
.pipeline-row small{margin-left:auto;color:#6b7280}
@keyframes pulse{50%{opacity:.4}}
</style>
