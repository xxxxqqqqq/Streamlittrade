<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import CandlestickTradeChart from '../components/CandlestickTradeChart.vue'
import TradeTimeline from '../components/TradeTimeline.vue'
import {BarChart3,BrainCircuit,CalendarDays,Database,GitBranch,RefreshCw,ShieldCheck} from 'lucide-vue-next'

const route=useRoute(),router=useRouter()
const models=ref<any[]>([]),modelId=ref(''),context=ref<any>(null),backtestId=ref(''),symbol=ref(''),timeline=ref<any>(null)
const loading=ref(true),error=ref(''),selected=ref<any>(null)
const activeRequest=computed(()=>context.value?.active_backtest?.request||timeline.value?.context?.request||null)
const selectedSignal=computed(()=>timeline.value?.signals?.find((item:any)=>item.date===selected.value?.date))
const selectedFactors=computed(()=>timeline.value?.factors?.find((item:any)=>item.date===selected.value?.date))
const factorEntries=computed(()=>Object.entries(selectedFactors.value||{}).filter(([key])=>key!=='date'))

async function loadContext(){
  loading.value=true;error.value='';timeline.value=null;selected.value=null
  try{
    context.value=(await api.get(`/models/${modelId.value}/trade-workbench/context`)).data
    const requested=String(route.query.backtest_id||'')
    backtestId.value=context.value.backtests.some((item:any)=>item.id===requested)?requested:(context.value.backtests[0]?.id||'')
    symbol.value=context.value.universe.includes(String(route.query.symbol||''))?String(route.query.symbol):context.value.universe[0]
    if(backtestId.value){
      context.value=(await api.get(`/models/${modelId.value}/trade-workbench/context`,{params:{backtest_id:backtestId.value}})).data
      await loadTimeline()
    }
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{loading.value=false}
}
async function loadTimeline(){
  if(!backtestId.value||!symbol.value)return
  loading.value=true;error.value=''
  try{
    timeline.value=(await api.get(`/backtests/${backtestId.value}/symbol-timeline`,{params:{symbol:symbol.value}})).data
    selected.value=timeline.value.events[0]||timeline.value.signals.find((item:any)=>item.selected)||timeline.value.signals.at(-1)||null
    router.replace({query:{...route.query,model_id:modelId.value,backtest_id:backtestId.value,symbol:symbol.value}})
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message;timeline.value=null}
  finally{loading.value=false}
}
async function changeModel(){await router.replace({path:'/trade-workbench',query:{model_id:modelId.value}});await loadContext()}
async function changeBacktest(){
  context.value=(await api.get(`/models/${modelId.value}/trade-workbench/context`,{params:{backtest_id:backtestId.value}})).data
  await loadTimeline()
}
function choosePoint(value:any){selected.value=value}
onMounted(async()=>{
  try{
    models.value=(await api.get('/models')).data.filter((item:any)=>item.prediction_artifact_uri)
    const requested=String(route.params.id||route.query.model_id||'')
    modelId.value=models.value.some(item=>item.id===requested)?requested:(models.value[0]?.id||'')
    if(modelId.value)await loadContext()
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message;loading.value=false}
})
</script>

<template>
  <section class="trade-workbench-page">
    <div class="page-intro"><div><span class="eyebrow">MODEL-TO-TRADE</span><h2>模型交易工作台</h2><p>把不可变因子、CV OOS 预测、横截面排名与真实回测成交放在同一条证据链上。</p></div><button class="primary" :disabled="!modelId" @click="router.push({path:'/backtests/new',query:{model_id:modelId}})"><BarChart3 :size="16"/>用此模型创建回测</button></div>
    <p v-if="error" class="error-box">{{error}}</p>
    <article class="panel workbench-picker"><div class="field"><label>模型版本</label><select v-model="modelId" @change="changeModel"><option v-for="item in models" :key="item.id" :value="item.id">{{item.name}} v{{item.version}} · {{item.algorithm}}</option></select></div><div class="field"><label>真实回测</label><select v-model="backtestId" @change="changeBacktest"><option v-for="item in context?.backtests||[]" :key="item.id" :value="item.id">{{item.created_at.slice(0,16).replace('T',' ')}} · {{item.start_date}} → {{item.end_date}}</option></select></div><div class="field"><label>股票</label><select v-model="symbol" @change="loadTimeline"><option v-for="item in context?.universe||[]" :key="item" :value="item">{{item}}</option></select></div><button class="secondary" :disabled="loading" @click="loadTimeline"><RefreshCw :size="15" :class="{spin:loading}"/>刷新</button></article>
    <div v-if="loading&&!context" class="panel empty">正在装配模型、数据与交易证据链…</div>
    <template v-else-if="context">
      <article class="research-context panel"><div><BrainCircuit :size="18"/><span>模型</span><b>{{context.model.name}} v{{context.model.version}}</b><small>{{context.model.algorithm}} · {{context.model.stage}}</small></div><div><Database :size="18"/><span>数据与因子</span><b>{{context.research.data_version_id.slice(0,8)}} / {{context.research.feature_snapshot_id.slice(0,8)}}</b><small>{{context.features.length}} 个因子 · {{context.universe.length}} 只股票</small></div><div><CalendarDays :size="18"/><span>预测目标</span><b>未来 {{context.prediction_target.horizon_trading_days}} 日上涨概率</b><small>{{context.evaluation.oos_start}} → {{context.evaluation.oos_end}}</small></div><div><ShieldCheck :size="18"/><span>评价边界</span><b>CV OOS · Purged Walk-Forward</b><small>不是最终封存检验区</small></div></article>
      <p class="oos-warning"><ShieldCheck :size="15"/>{{context.evaluation.warning}}</p>
      <div v-if="activeRequest" class="config-strip"><span>Top {{activeRequest.top_n}}</span><span>阈值 {{Number(activeRequest.minimum_probability||0)*100}}%</span><span>每 {{activeRequest.rebalance_frequency}} 个交易日调仓</span><span>佣金 {{Number(activeRequest.commission||0)*100}}%</span><span>印花税 {{Number(activeRequest.stamp_duty||0)*100}}%</span><span>滑点 {{Number(activeRequest.slippage||0)*100}}%</span><span>T+1 · {{activeRequest.lot_size||100}} 股整手</span></div>
      <div v-if="!context.backtests.length" class="panel empty"><h3>该模型还没有可信组合回测</h3><p>先使用固定快照创建回测，完成后即可展示真实买卖点。</p><button class="primary" @click="router.push({path:'/backtests/new',query:{model_id:modelId}})">创建模型回测</button></div>
      <template v-else-if="timeline">
        <div class="workbench-main"><article class="panel chart-panel"><CandlestickTradeChart :bars="timeline.bars" :signals="timeline.signals" :events="timeline.events" @select="choosePoint"/></article><aside class="panel explanation-panel"><div class="panel-head"><div><h3>{{selected?.date||'选择一个交易点'}}</h3><p>结构化数据解释，不使用生成式猜测</p></div><GitBranch :size="18"/></div><template v-if="selected"><dl class="detail-list"><div><dt>OOS 上涨概率</dt><dd>{{selectedSignal?`${(Number(selectedSignal.probability)*100).toFixed(2)}%`:'—'}}</dd></div><div><dt>横截面排名</dt><dd>{{selectedSignal?`${selectedSignal.rank} / ${selectedSignal.universe_size}`:'—'}}</dd></div><div><dt>组合决策</dt><dd>{{selectedSignal?.reason||selected.reason||'—'}}</dd></div><div><dt>信号 / 成交</dt><dd>{{selected.signal_date||selected.date}} → {{selected.action?selected.date:'—'}}</dd></div><div v-if="selected.action"><dt>事件</dt><dd>{{selected.action}} · {{selected.shares||'—'}} 股 @ {{selected.price||'—'}}</dd></div><div v-if="selected.pnl!==undefined"><dt>扣费后损益</dt><dd>{{Number(selected.pnl).toFixed(2)}} 元</dd></div></dl><h4>当日因子原始值</h4><div class="factor-values"><span v-for="[key,value] in factorEntries" :key="key"><b>{{key}}</b><code>{{value===null?'—':Number(value).toFixed(6)}}</code></span></div><p v-if="!factorEntries.length" class="empty compact">该日期没有可用因子值。</p><p class="phase-note">局部正负贡献将在解释增强阶段加入；当前不伪造模型贡献。</p></template></aside></div>
        <article class="panel"><div class="panel-head"><div><h3>信号到成交时间线</h3><p>T 日收盘预测与 T+1 实际成交明确分离</p></div></div><TradeTimeline :events="timeline.events"/></article>
      </template>
    </template>
  </section>
</template>
