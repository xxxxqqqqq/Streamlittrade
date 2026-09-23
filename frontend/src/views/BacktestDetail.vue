<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import SectionTabs from '../components/SectionTabs.vue'
import GuideCard from '../components/GuideCard.vue'
import VerdictCard from '../components/VerdictCard.vue'
import {excessReturnVerdict,selectionVerdict} from '../verdict'
import {backtestTabs} from '../sections'
import {ArrowLeft,BrainCircuit,CalendarDays,Coins,Database,LineChart,ReceiptText,ShieldCheck} from 'lucide-vue-next'

const route=useRoute(),router=useRouter(),run=ref<any>(null),artifact=ref<any>(null),loading=ref(true),error=ref('')
onMounted(async()=>{
  try{
    const id=String(route.params.id)
    const [meta,result]=await Promise.all([api.get(`/backtests/${id}`),api.get(`/backtests/${id}/artifact`)])
    run.value=meta.data;artifact.value=result.data
  }catch(e:any){error.value=e.response?.data?.detail||e.message}
  finally{loading.value=false}
})
const metrics=computed(()=>run.value?.metrics||{}),quality=computed(()=>run.value?.data_quality||{}),equity=computed(()=>artifact.value?.equity||[])
const modelMode=computed(()=>run.value?.signal_source==='model_oos')
const modelLineage=computed(()=>artifact.value?.audit?.model_lineage||{})
const construction=computed(()=>artifact.value?.audit?.portfolio_construction||{})
const predictionScope=computed(()=>construction.value.prediction_scope||modelLineage.value.prediction_scope||'tuning_oos')
const sealedMode=computed(()=>modelMode.value&&predictionScope.value==='sealed_oos')
const scopeName=computed(()=>sealedMode.value?'终检':'验证区')
// 回测账本里的收益都是百分数（3.81 = 3.81%），判断层用小数口径，这里统一换算。
const excessRatio=computed(()=>typeof metrics.value.excess_return==='number'?metrics.value.excess_return/100:null)
const tradeCount=computed(()=>Number(metrics.value.turnover_events??metrics.value.total_trades??0))
const verdict=computed(()=>selectionVerdict(tradeCount.value>0)??excessReturnVerdict(excessRatio.value,tradeCount.value))
const headline=computed(()=>{
  if(verdict.value.level==='na')return tradeCount.value>0?'结论：账本数据不完整，暂时给不出判断':'结论：这段时间没有标的入选（全现金，本身就是有效结论）'
  if(verdict.value.level==='good')return '结论：这段时间这个模型跑赢基准'
  if(verdict.value.level==='ok')return '结论：这段时间这个模型小幅跑赢基准'
  return '结论：这个模型目前不赚钱'
})
function signed(value:any){return typeof value==='number'&&Number.isFinite(value)?`${value>0?'+':''}${value.toFixed(2)}%`:'—'}
const conclusion=computed(()=>{
  const total=metrics.value.total_return,benchmark=metrics.value.benchmark_return,excess=metrics.value.excess_return
  if(typeof total!=='number'||typeof benchmark!=='number')return '账本里没有收益数据，无法给出结论。'
  const gap=typeof excess==='number'?Math.abs(excess).toFixed(2):'—'
  const direction=(excess??0)>=0?'跑赢':'跑输'
  const trades=tradeCount.value
  const winRate=typeof metrics.value.win_rate==='number'?`${metrics.value.win_rate.toFixed(0)}%`:'—'
  const details=trades>0
    ? `${trades} 笔成交，胜率 ${winRate}（按报告的成交约束模型扣完手续费、印花税和滑点）`
    : '没有任何成交（没有标的达到预登记入选线）'
  return `模型组合 ${signed(total)}，基准 ${signed(benchmark)}，${direction} ${gap} 个点。${details}。`
})
const validationLabels:Record<string,string>={
  final_sealed_holdout:'终检（一次性，不可重来）',
  three_way_purged_walk_forward:'三段式时间序列验证',
  purged_walk_forward_oos:'时间序列样本外验证',
}
function validationLabel(value:any){return validationLabels[String(value)]||String(value||'—')}
function scopeLabel(value:any){return value==='sealed_oos'?'终检区':value==='tuning_oos'?'验证区':String(value||'—')}
// 质量警告是机器枚举，界面统一翻成中文再展示。
const WARNING_LABELS:Record<string,string>={
  duplicate_dates:'存在重复交易日',
  missing_required_values:'关键字段缺失',
  invalid_ohlc:'最高/最低价与开收盘价矛盾',
  nonpositive_prices:'出现非正价格',
  unbalanced_symbol_calendar:'个股交易日历不齐（停牌或未上市）',
}
const warningText=computed(()=>{
  const warnings=(quality.value.warnings||[]) as string[]
  return warnings.length?warnings.map(item=>WARNING_LABELS[item]||item).join('；'):'无'
})
const chartPoints=computed(()=>{
  if(!equity.value.length)return''
  const values=equity.value.map((item:any)=>Number(item.value)),min=Math.min(...values),max=Math.max(...values),range=max-min||1
  return values.map((value:number,index:number)=>`${index/(values.length-1||1)*1000},${220-(value-min)/range*200}`).join(' ')
})
const cards=computed(()=>[
  ['总收益率',metrics.value.total_return,'%'],['年化收益率',metrics.value.annual_return,'%'],
  ['最大回撤',metrics.value.max_drawdown,'%'],['夏普比率',metrics.value.sharpe_ratio,''],
  ['超额收益',metrics.value.excess_return,'%'],['信息比率',metrics.value.information_ratio,''],
  [modelMode.value?'调仓次数':'拒单数量',modelMode.value?metrics.value.rebalance_count:metrics.value.rejected_orders,''],
  ['成交事件',metrics.value.turnover_events??metrics.value.total_trades,''],
])
function show(value:any,suffix=''){return value===null||value===undefined?'—':`${value}${suffix}`}
</script>

<template>
  <section>
    <SectionTabs :tabs="backtestTabs" label="回测段页签"/>
    <GuideCard
      :icon="LineChart"
      title="这一步在干什么"
      text="用模型没见过的数据模拟真实买卖（T+1、整手、手续费全算），看赚不赚钱。日期区间由平台锁定，不能挑好日子。"
    />
    <div class="crumb"><button @click="router.push('/backtests')"><ArrowLeft :size="15"/>返回回测中心</button><span>组合级可信回测报告</span></div>
    <div v-if="loading" class="panel empty">正在加载报告…</div>
    <div v-else-if="error" class="panel error-box">{{error}}</div>
    <template v-else>
      <VerdictCard :level="verdict.level">
        <b>{{headline}}</b>
        <p>{{run.start_date}} 至 {{run.end_date}}：{{conclusion}}</p>
        <p class="verdict-hint">判断依据：{{verdict.hint}}</p>
      </VerdictCard>
      <article class="report-head">
        <div>
          <span class="eyebrow dark">{{modelMode?(sealedMode?'终检报告':'验证区报告'):run.run_type==='portfolio'?'组合回测报告':'单标的回测报告'}}</span>
          <h2>{{modelMode?modelLineage.model_name:run.symbol}} · {{modelMode?`${scopeName}概率组合`:run.strategy_name}}</h2>
          <p>{{run.start_date}} 至 {{run.end_date}}</p>
        </div>
        <div class="report-meta"><span><Coins :size="15"/>初始资金 ¥{{Number(run.initial_cash).toLocaleString()}}</span><span><CalendarDays :size="15"/>{{new Date(run.created_at).toLocaleString()}}</span></div>
      </article>
      <article v-if="modelMode" class="panel">
        <div class="panel-head"><div><h3>{{scopeName}}结果说明</h3><p>{{sealedMode?'这是完整终检结果：一次性、不可重来，不应再据此修改模型或参数。':'这是验证区结果，可以反复比较不同方案，但不能当作最终未见样本的表现。'}}</p></div><ShieldCheck :size="19"/></div>
        <div class="config-strip"><span>预测范围 {{modelLineage.prediction_start||run.start_date}} → {{modelLineage.prediction_end||run.end_date}}</span><span>日期区间由平台锁定，不能挑好日子（防自欺）</span><span>组合规则：{{modelLineage.portfolio_protocol_source||construction.portfolio_protocol_source}}</span></div>
      </article>
      <div class="result-grid"><article class="panel metric-result" v-for="[label,value,suffix] in cards" :key="String(label)"><small>{{label}}</small><strong>{{show(value,String(suffix))}}</strong></article></div>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>数据质量门禁</h3><p>回测前标准化并拒绝不可解释的坏数据</p></div><Database :size="19"/></div><dl class="detail-list"><div><dt>标的 / 行数</dt><dd>{{quality.symbol_count}} / {{quality.row_count}}</dd></div><div><dt>日期范围</dt><dd>{{quality.date_min}} → {{quality.date_max}}</dd></div><div><dt>停牌记录</dt><dd>{{quality.suspended_rows||0}}</dd></div><div><dt>日历缺口</dt><dd>{{quality.missing_calendar_rows||0}}</dd></div><div><dt>质量警告</dt><dd>{{warningText}}</dd></div></dl></article>
        <article class="panel"><div class="panel-head"><div><h3>成交约束模型</h3><p>报告产物中保留完整规则快照</p></div><ShieldCheck :size="19"/></div><dl class="detail-list"><div><dt>信号成交</dt><dd>下一交易日开盘</dd></div><div><dt>交收规则</dt><dd>T+1</dd></div><div><dt>涨跌停 / 停牌</dt><dd>拒绝成交并记录原因</dd></div><div><dt>最大参与率</dt><dd>{{metrics.max_volume_participation?metrics.max_volume_participation*100:'—'}}%</dd></div></dl></article>
        <article v-if="modelMode" class="panel"><div class="panel-head"><div><h3>模型与预测血缘</h3><p>明确区分验证区结果与终检结果</p></div><BrainCircuit :size="19"/></div><dl class="detail-list"><div><dt>模型 / 算法</dt><dd>{{modelLineage.model_name}} v{{modelLineage.model_version}} / {{modelLineage.algorithm}}</dd></div><div><dt>预测作用域</dt><dd>{{scopeLabel(predictionScope)}}</dd></div><div><dt>验证方式</dt><dd>{{validationLabel(modelLineage.validation)}}</dd></div><div><dt>模型哈希</dt><dd>{{modelLineage.model_sha256?.slice(0,16)}}</dd></div><div><dt>预测哈希</dt><dd>{{modelLineage.prediction_sha256?.slice(0,16)}}</dd></div><div><dt>数据版本</dt><dd>{{modelLineage.data_version_id?.slice(0,8)}}</dd></div></dl></article>
        <article v-if="modelMode" class="panel"><div class="panel-head"><div><h3>组合构建规则</h3><p>所有选股和调仓参数均固化在报告中</p></div><ShieldCheck :size="19"/></div><dl class="detail-list"><div><dt>选股方法</dt><dd>概率 Top-N</dd></div><div><dt>持仓 / 最低概率</dt><dd>{{construction.top_n}} / {{construction.minimum_probability}}</dd></div><div><dt>调仓频率</dt><dd>{{construction.rebalance_frequency}} 个交易日</dd></div><div><dt>调仓次数</dt><dd>{{construction.rebalance_count}}</dd></div><div><dt>预测覆盖</dt><dd>{{construction.prediction_rows}} 行 / {{construction.prediction_dates}} 日</dd></div></dl></article>
      </div>
      <article class="panel"><div class="panel-head"><div><h3>组合净值曲线</h3><p>共享现金、费用和逐日持仓统一计价</p></div><LineChart :size="19"/></div><svg class="research-chart" viewBox="0 0 1000 240" preserveAspectRatio="none"><polyline :points="chartPoints" fill="none" stroke="#2679da" stroke-width="3" vector-effect="non-scaling-stroke"/></svg></article>
      <article class="panel trade-panel"><div class="panel-head"><div><h3>成交与拒单明细</h3><p>共 {{artifact.trades?.length||0}} 条审计事件</p></div><ReceiptText :size="19"/></div><div class="trade-table"><div class="trade-row trade-header"><span>日期</span><span>标的 / 动作</span><span>价格</span><span>数量</span><span>损益 / 原因</span></div><div class="trade-row" v-for="(trade,index) in artifact.trades" :key="index"><span>{{String(trade.date||'—').slice(0,10)}}</span><span>{{trade.symbol||run.symbol}} / {{trade.action||'—'}}</span><span>{{trade.price??'—'}}</span><span>{{trade.shares??trade.size??'—'}}</span><span>{{trade.pnl??trade.reason??'—'}}</span></div></div></article>
    </template>
  </section>
</template>

<style scoped>
.verdict-hint{margin-top:5px!important;color:#8b97a7!important;font-size:11px!important}
</style>
