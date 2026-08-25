<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {pollJobUntilTerminal} from '../jobPolling'
import {ArrowLeft,BarChart3,BrainCircuit,CheckCircle2,LoaderCircle} from 'lucide-vue-next'

const route=useRoute(),router=useRouter()
const submitting=ref(false),error=ref(''),job=ref<any>(null),backtestId=ref(''),longRunning=ref(false)
const versions=ref<any[]>([]),strategies=ref<any[]>([]),models=ref<any[]>([]),sealed=ref<any>(null)
const sealedLoading=ref(false),initialized=ref(false)
const form=ref({
  signal_source:'strategy',prediction_scope:'tuning_oos',model_id:'',run_type:'portfolio',data_source:'data_version',data_version_id:'',strategy_id:'',
  symbol:'',symbols:'',strategy_name:'right_trend',start_date:'2020-01-01',end_date:'2024-12-31',
  initial_cash:1000000,max_positions:5,max_volume_participation:0.05,
  lot_size:100,commission:0.0003,minimum_commission:5,stamp_duty:0.0005,slippage:0.001,
  top_n:5,minimum_probability:0.55,rebalance_frequency:5,
  ma_short:5,ma_mid:20,ma_long:60,vol_ratio:1.5,
  lookback:10,drop_threshold:0.08,rebound_threshold:0.03,confirm_days:2,
})

const selectedVersion=computed(()=>versions.value.find(item=>item.id===form.value.data_version_id))
const selectedStrategy=computed(()=>strategies.value.find(item=>item.id===form.value.strategy_id))
const selectedModel=computed(()=>models.value.find(item=>item.id===form.value.model_id))
const modelMode=computed(()=>form.value.signal_source==='model_oos')
const sealedMode=computed(()=>modelMode.value&&form.value.prediction_scope==='sealed_oos')
const sealedAvailable=computed(()=>
  sealed.value?.status==='succeeded'&&
  Boolean(sealed.value?.artifact_uri)&&
  sealed.value?.metrics?.evaluation_scope==='final_sealed_holdout'
)
const sealedStatusText=computed(()=>{
  if(sealedLoading.value)return '正在检查封存状态'
  if(!sealed.value)return '所选模型尚未开启最终封存区'
  if(sealed.value.status==='queued')return '最终封存评估正在排队'
  if(sealed.value.status==='running')return '最终封存评估正在运行'
  if(sealed.value.status==='failed')return '最终封存评估失败，请到模型详情查看原因'
  if(sealed.value.status!=='succeeded')return `最终封存评估状态：${sealed.value.status}`
  if(!sealed.value.artifact_uri)return '最终封存预测产物缺失'
  if(sealed.value.metrics?.evaluation_scope!=='final_sealed_holdout')return '最终封存评估结果不完整'
  return '最终封存区已就绪；日期和组合规则将使用封存前登记值'
})
const versionedMode=computed(()=>form.value.data_source==='data_version')
const effectiveImplementation=computed(()=>selectedStrategy.value?.implementation||form.value.strategy_name)
const isTrend=computed(()=>effectiveImplementation.value==='right_trend')

function applyDataVersion(){
  const version=selectedVersion.value
  if(!version)return
  const symbols=version.specification?.symbols||[]
  form.value.symbols=symbols.join(',')
  form.value.symbol=symbols[0]||''
  form.value.start_date=version.specification?.start_date||form.value.start_date
  form.value.end_date=version.specification?.end_date||form.value.end_date
}

function applyModelScope(){
  if(form.value.prediction_scope==='sealed_oos'&&sealedAvailable.value){
    const protocol=sealed.value.metrics?.portfolio_protocol||{}
    for(const key of ['top_n','minimum_probability','rebalance_frequency','initial_cash','max_volume_participation','lot_size','commission','minimum_commission','stamp_duty','slippage']){
      if(protocol[key]!==undefined)(form.value as any)[key]=protocol[key]
    }
    form.value.start_date=sealed.value.metrics?.sealed_start||form.value.start_date
    form.value.end_date=sealed.value.metrics?.sealed_end||form.value.end_date
  }else{
    if(form.value.prediction_scope==='sealed_oos')form.value.prediction_scope='tuning_oos'
    const tuning=selectedModel.value.metrics?.research_split?.tuning||{}
    form.value.start_date=tuning.start||form.value.start_date
    form.value.end_date=tuning.end||form.value.end_date
  }
}

let sealedRequest=0
async function loadSealedEvaluation(){
  const model=selectedModel.value
  const request=++sealedRequest
  sealed.value=null
  if(!model){applyModelScope();return}
  sealedLoading.value=true
  try{
    const response=await api.get(`/models/${model.id}/sealed-evaluation`)
    if(request!==sealedRequest)return
    sealed.value=response.data
    applyModelScope()
  }finally{
    if(request===sealedRequest)sealedLoading.value=false
  }
}

onMounted(async()=>{
  try{
    const [versionResponse,strategyResponse,modelResponse]=await Promise.all([
      api.get('/data-center/versions'),api.get('/strategies'),api.get('/models'),
    ])
    versions.value=versionResponse.data.filter((item:any)=>item.layer==='standardized'&&item.status==='ready')
    strategies.value=strategyResponse.data
    models.value=modelResponse.data.filter((item:any)=>Boolean(item.prediction_artifact_uri))
    if(versions.value.length){form.value.data_version_id=versions.value[0].id;applyDataVersion()}
    else{form.value.data_source='demo';form.value.symbol='DEMO';form.value.symbols='DEMO1,DEMO2,DEMO3,DEMO4,DEMO5'}
    if(strategies.value.length)form.value.strategy_id=strategies.value[0].id
    if(models.value.length){
      const requested=String(route.query.model_id||'')
      form.value.model_id=models.value.some((item:any)=>item.id===requested)?requested:models.value[0].id
      if(requested&&form.value.model_id===requested)form.value.signal_source='model_oos'
      const requestedScope=String(route.query.prediction_scope||'')
      if(requestedScope==='sealed_oos')form.value.prediction_scope='sealed_oos'
      await loadSealedEvaluation()
    }
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{initialized.value=true}
})
watch(()=>form.value.data_version_id,applyDataVersion)
watch(()=>form.value.model_id,()=>{if(initialized.value)loadSealedEvaluation().catch(exception=>{error.value=exception.response?.data?.detail||exception.message})})
watch(()=>form.value.prediction_scope,applyModelScope)

async function submit(){
  submitting.value=true;error.value='';longRunning.value=false
  try{
    const parameters=isTrend.value
      ? {ma_short:Number(form.value.ma_short),ma_mid:Number(form.value.ma_mid),ma_long:Number(form.value.ma_long),vol_ratio:Number(form.value.vol_ratio)}
      : {lookback:Number(form.value.lookback),drop_threshold:Number(form.value.drop_threshold),rebound_threshold:Number(form.value.rebound_threshold),confirm_days:Number(form.value.confirm_days),vol_ratio:Number(form.value.vol_ratio)}
    const body={
      ...form.value,
      model_id:modelMode.value?form.value.model_id:null,
      strategy_id:modelMode.value?null:(form.value.strategy_id||null),
      strategy_name:effectiveImplementation.value,
      data_version_id:!modelMode.value&&versionedMode.value?form.value.data_version_id:null,
      symbols:form.value.symbols.split(',').map(symbol=>symbol.trim()).filter(Boolean),
      strategy_parameters:modelMode.value?{}:parameters,
    }
    const response=await api.post('/backtests',body)
    backtestId.value=response.data.backtest_id
    job.value=await pollJobUntilTerminal(
      async()=>(await api.get(`/jobs/${response.data.job_id}`)).data,
      {onUpdate:value=>job.value=value,onLongRunning:()=>longRunning.value=true},
    )
    if(job.value.status!=='succeeded')throw new Error(job.value.error_message||'回测失败')
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{submitting.value=false}
}
</script>

<template>
  <section class="workflow">
    <div class="crumb"><button @click="router.push('/backtests')"><ArrowLeft :size="15"/>返回回测中心</button><span>组合级可信回测</span></div>
    <article class="panel form-card">
      <div class="form-heading"><div class="feature-icon"><BrainCircuit v-if="modelMode" :size="23"/><BarChart3 v-else :size="23"/></div><div><h2>{{modelMode?'创建模型组合回测':'创建可复现策略回测'}}</h2><p>{{modelMode?'使用 Purged Walk-Forward 产生的样本外概率构建组合，自动锁定模型训练时的数据血缘。':'绑定不可变数据版本与策略版本，历史结果不会被后续参数修改污染。'}}</p></div></div>
      <form v-if="job?.status!=='succeeded'" @submit.prevent="submit">
        <div class="form-grid">
          <div class="field full"><label>信号来源</label><select v-model="form.signal_source"><option value="strategy">规则策略</option><option value="model_oos" :disabled="!models.length">模型样本外预测（推荐用于模型评估）</option></select><small v-if="!models.length">当前项目还没有包含样本外预测的已训练模型。</small></div>
          <template v-if="modelMode">
            <div class="field full"><label>已登记模型</label><select v-model="form.model_id"><option v-for="model in models" :key="model.id" :value="model.id">{{model.name}} · {{model.algorithm}} · {{model.stage}} · AUC {{model.metrics?.roc_auc??'—'}}</option></select><small v-if="selectedModel">模型 {{selectedModel.id.slice(0,8)}} 的预测、数据版本和完整时间范围将写入审计血缘。</small></div>
            <div class="field full"><label>评估区间</label><select v-model="form.prediction_scope"><option value="tuning_oos">调参区样本外回测（用于比较和调整组合规则）</option><option value="sealed_oos" :disabled="!sealedAvailable">最终封存区回测（一次性最终检验）</option></select><small>{{sealedMode?'使用封存前锁定的完整区间和组合参数，页面与服务端均禁止修改。':sealedStatusText+'；调参区必须使用完整区间，不能把结果称为最终表现。'}}</small></div>
            <div class="field"><label>Top-N 持仓数量</label><input v-model.number="form.top_n" type="number" min="1" max="100" :disabled="sealedMode"/></div>
            <div class="field"><label>最低入选概率</label><input v-model.number="form.minimum_probability" type="number" min="0" max="1" step="0.01" :disabled="sealedMode"/></div>
            <div class="field"><label>调仓频率（交易日）</label><input v-model.number="form.rebalance_frequency" type="number" min="1" max="60" :disabled="sealedMode"/></div>
            <div class="field"><label>组合权重</label><input value="等权重" disabled/></div>
          </template>
          <div v-if="!modelMode" class="field"><label>回测类型</label><select v-model="form.run_type"><option value="portfolio">多标的组合</option><option value="single">单标的兼容模式</option></select></div>
          <div v-if="!modelMode" class="field"><label>数据来源</label><select v-model="form.data_source"><option value="data_version" :disabled="!versions.length">标准化数据版本（推荐）</option><option value="demo">演示行情</option><option value="baostock">Baostock 兼容模式</option></select></div>
          <div v-if="!modelMode&&versionedMode" class="field full"><label>标准化数据版本</label><select v-model="form.data_version_id"><option v-for="version in versions" :key="version.id" :value="version.id">{{version.content_sha256?.slice(0,12)}} · {{version.row_count}} 行 · {{version.specification?.start_date}} 至 {{version.specification?.end_date}}</option></select></div>
          <div v-if="!modelMode&&form.run_type==='single'" class="field full"><label>证券代码</label><select v-if="versionedMode" v-model="form.symbol"><option v-for="symbol in selectedVersion?.specification?.symbols||[]" :key="symbol" :value="symbol">{{symbol}}</option></select><input v-else v-model="form.symbol" :disabled="form.data_source==='demo'"/></div>
          <div v-else-if="!modelMode" class="field full"><label>证券代码列表</label><input v-model="form.symbols" :readonly="versionedMode" :disabled="form.data_source==='demo'"/><small>{{versionedMode?'股票池来自所选不可变数据版本。':'多个代码以逗号分隔。'}}</small></div>
          <div v-if="!modelMode" class="field full"><label>已登记策略版本（推荐）</label><select v-model="form.strategy_id"><option value="">临时参数，不绑定策略版本</option><option v-for="strategy in strategies" :key="strategy.id" :value="strategy.id">{{strategy.name}} · {{strategy.slug}} v{{strategy.version}} · {{strategy.implementation}}</option></select><small v-if="selectedStrategy">本次回测将使用该版本保存的参数：{{JSON.stringify(selectedStrategy.parameters)}}</small></div>
          <div v-if="!modelMode&&!selectedStrategy" class="field full"><label>临时交易策略</label><select v-model="form.strategy_name"><option value="right_trend">右侧趋势策略</option><option value="v_shape">V 型反转策略</option></select></div>
          <template v-if="!modelMode&&!selectedStrategy&&isTrend">
            <div class="field"><label>短期均线</label><input v-model.number="form.ma_short" type="number" min="2"/></div>
            <div class="field"><label>中期均线</label><input v-model.number="form.ma_mid" type="number" min="3"/></div>
            <div class="field"><label>长期均线</label><input v-model.number="form.ma_long" type="number" min="4"/></div>
          </template>
          <template v-else-if="!modelMode&&!selectedStrategy">
            <div class="field"><label>回看周期</label><input v-model.number="form.lookback" type="number" min="3"/></div>
            <div class="field"><label>下跌阈值</label><input v-model.number="form.drop_threshold" type="number" step="0.01"/></div>
            <div class="field"><label>反弹阈值</label><input v-model.number="form.rebound_threshold" type="number" step="0.01"/></div>
          </template>
          <div v-if="!modelMode" class="field"><label>最大持仓数</label><input v-model.number="form.max_positions" type="number" min="1" max="100" :disabled="form.run_type==='single'"/></div>
          <div class="field"><label>最大成交量参与率</label><input v-model.number="form.max_volume_participation" type="number" min="0.001" max="1" step="0.01" :disabled="form.run_type==='single'||sealedMode"/></div>
          <div class="field"><label>整手股数</label><input v-model.number="form.lot_size" type="number" min="100" step="100" :disabled="sealedMode"/></div>
          <div class="field"><label>买卖佣金率</label><input v-model.number="form.commission" type="number" min="0" max="0.05" step="0.0001" :disabled="sealedMode"/></div>
          <div class="field"><label>最低佣金</label><input v-model.number="form.minimum_commission" type="number" min="0" step="1" :disabled="sealedMode"/></div>
          <div class="field"><label>卖出印花税率</label><input v-model.number="form.stamp_duty" type="number" min="0" max="0.05" step="0.0001" :disabled="sealedMode"/></div>
          <div class="field"><label>单边滑点率</label><input v-model.number="form.slippage" type="number" min="0" max="0.1" step="0.0001" :disabled="sealedMode"/></div>
          <div class="field"><label>初始资金</label><input v-model.number="form.initial_cash" type="number" min="1000" :disabled="sealedMode"/></div>
          <div class="field"><label>开始日期</label><input v-model="form.start_date" type="date" :disabled="modelMode"/></div>
          <div class="field"><label>结束日期</label><input v-model="form.end_date" type="date" :disabled="modelMode"/></div>
        </div>
        <div v-if="job" class="job-progress"><div><LoaderCircle :size="17" class="spin"/><span>{{job.status==='queued'?'等待回测资源':modelMode?'正在构建模型选股组合并计算可信账本':'正在读取版本化行情并计算账本'}}</span><b>{{job.progress}}%</b></div><div class="progress-track"><i :style="{width:job.progress+'%'}"></i></div></div>
        <div v-if="longRunning" class="background-task-note">回测仍在后台运行。可以继续等待，或前往 <button type="button" class="text-button" @click="router.push('/jobs')">任务中心</button> 查看进度；离开本页不会取消任务。</div>
        <p v-if="error" class="error-box">{{error}}</p>
        <div class="form-actions"><button type="button" class="secondary" @click="router.push('/backtests')">取消</button><button class="primary" :disabled="submitting||(modelMode?!form.model_id:versionedMode&&!form.data_version_id)"><LoaderCircle v-if="submitting" :size="16" class="spin"/><BarChart3 v-else :size="16"/>{{submitting?'正在回测':'运行回测'}}</button></div>
      </form>
      <div v-else class="success-state"><CheckCircle2 :size="48"/><h3>组合回测已完成</h3><p>{{modelMode?'模型、OOS 预测、组合构建参数、数据血缘和资金账本均已保存。':'数据、策略版本、资金账本与质量报告均已保存。'}}</p><button class="primary" @click="router.push('/backtests/'+backtestId)">查看完整报告</button></div>
    </article>
  </section>
</template>
