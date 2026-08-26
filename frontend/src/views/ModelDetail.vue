<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {pollJobUntilTerminal} from '../jobPolling'
import {user} from '../auth'
import {ArrowLeft,Boxes,CalendarDays,Database,GitBranch,RotateCcw,ShieldCheck,Sparkles} from 'lucide-vue-next'

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
const metricCards=computed(()=>[
  ['ROC AUC',metrics.value.roc_auc,'percent'],['Rank IC',metrics.value.rank_ic,'number'],
  ['成本后收益',metrics.value.cost_adjusted_return,'percent'],['超额收益',metrics.value.excess_return,'percent'],
  ['年化夏普',metrics.value.annualized_sharpe,'number'],['换手率',metrics.value.turnover,'percent'],
])
function display(value:any,type:string){if(value===undefined||value===null)return '—';return type==='percent'?(Number(value)*100).toFixed(2)+'%':Number(value).toFixed(3)}
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
    if(job.status!=='succeeded')throw new Error(job.error_message||'最终封存区评估未完成')
    sealed.value=(await api.get(`/models/${model.value.id}/sealed-evaluation`)).data
    model.value=(await api.get(`/models/${route.params.id}/detail`)).data
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{changing.value=false}
}
</script>

<template>
  <section class="workflow">
    <div class="crumb"><button @click="router.push('/models')"><ArrowLeft :size="15"/>返回模型仓库</button><span>研究流程 · 第 3/3 步</span></div>
    <div v-if="loading" class="panel empty">正在读取模型结果…</div>
    <div v-else-if="error&&!model" class="panel error-box">{{error}}</div>
    <template v-else>
      <article class="model-hero"><div class="feature-icon purple-bg"><Boxes :size="25"/></div><div><span class="eyebrow dark">REGISTERED MODEL</span><h2>{{model.name}}</h2><p>{{model.algorithm}} · Version {{model.version}}</p></div><div class="row-actions"><button v-if="model.prediction_artifact_uri" class="primary" @click="router.push(`/models/${model.id}/trade-workbench`)">模型交易工作台</button><button v-if="model.prediction_artifact_uri" class="secondary" @click="router.push({path:'/backtests/new',query:{model_id:model.id,prediction_scope:'tuning_oos'}})">调参区回测</button><button v-if="sealed?.status==='succeeded'" class="secondary" @click="router.push({path:'/backtests/new',query:{model_id:model.id,prediction_scope:'sealed_oos'}})">最终封存区回测</button></div><i class="status" :class="model.stage">{{model.stage}}</i></article>
      <div class="result-grid"><article class="panel metric-result" v-for="[label,value,type] in metricCards" :key="String(label)"><small>{{label}}</small><strong>{{display(value,String(type))}}</strong></article></div>
      <article v-if="calibration.bins" class="panel"><div class="panel-head"><div><h3>概率校准与可靠性</h3><p>调参区 OOS 概率；Brier / Log Loss 越低越好，ECE 衡量预测概率与实际频率的偏差。</p></div><ShieldCheck :size="18"/></div><div class="config-strip"><span>校准后 Brier {{calibration.brier_score}}</span><span>原始 Brier {{calibration.raw_brier_score}}</span><span>校准后 Log Loss {{calibration.log_loss}}</span><span>ECE {{calibration.expected_calibration_error}}</span></div><div class="artifact" v-for="bin in calibration.bins" :key="bin.lower"><code>{{Math.round(bin.lower*100)}}%–{{Math.round(bin.upper*100)}}% · 预测 {{display(bin.mean_probability,'percent')}} · 实际 {{display(bin.observed_frequency,'percent')}} · n={{bin.count}}</code></div></article>
      <article v-if="metrics.evaluation_scope==='tuning_oos'" class="panel"><div class="panel-head"><div><h3>三段式研究边界</h3><p>训练和调参结果可反复比较；最终封存区只能交给一个锁定模型。</p></div><ShieldCheck :size="18"/></div><div class="config-strip"><span>训练 {{metrics.research_split?.training?.start}} → {{metrics.research_split?.training?.end}}</span><span>调参 {{metrics.research_split?.tuning?.start}} → {{metrics.research_split?.tuning?.end}}</span><span>封存 {{metrics.research_split?.sealed?.start}} → {{metrics.research_split?.sealed?.end}}</span><span>{{sealed?.status==='succeeded'?'封存区已开启':'封存区锁定中'}}</span></div><template v-if="!sealed&&user?.role==='admin'"><p>开启封存区前必须先登记组合规则；开启后参数与日期永久锁定，避免看到最终结果后再调参。</p><div class="config-strip"><label>Top-N <input v-model.number="sealedProtocol.top_n" type="number" min="1" max="100"/></label><label>最低概率 <input v-model.number="sealedProtocol.minimum_probability" type="number" min="0" max="1" step="0.01"/></label><label>调仓日 <input v-model.number="sealedProtocol.rebalance_frequency" type="number" min="1" max="60"/></label><label>初始资金 <input v-model.number="sealedProtocol.initial_cash" type="number" min="1000"/></label></div><button class="primary" :disabled="changing" @click="openSealed"><ShieldCheck :size="15"/>锁定模型、组合参数并开启最终封存区</button></template><div v-if="sealed?.metrics" class="result-grid"><article class="metric"><small>封存 ROC AUC</small><strong>{{display(sealed.metrics.roc_auc,'percent')}}</strong></article><article class="metric"><small>封存 Rank IC</small><strong>{{display(sealed.metrics.rank_ic,'number')}}</strong></article><article class="metric"><small>封存超额收益</small><strong>{{display(sealed.metrics.excess_return,'percent')}}</strong></article></div><p v-if="sealed?.metrics">组合规则：{{JSON.stringify(sealed.metrics.portfolio_protocol||sealedProtocol)}} · {{sealed.metrics.portfolio_protocol_source==='preregistered'?'封存前已登记':'历史封存记录：使用系统默认规则，未在封存前登记'}}</p></article>
      <article v-if="sealed?.metrics?.calibration" class="panel"><div class="panel-head"><div><h3>最终封存区概率门禁</h3><p>该结果只生成一次，用于确认概率可靠性没有在真正未见数据上失效。</p></div></div><div class="config-strip"><span>Brier {{sealed.metrics.calibration.brier_score}}</span><span>Raw Brier {{sealed.metrics.calibration.raw_brier_score}}</span><span>Log Loss {{sealed.metrics.calibration.log_loss}}</span><span>ECE {{sealed.metrics.calibration.expected_calibration_error}}</span></div></article>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>{{metrics.evaluation_scope==='tuning_oos'?'调参区验证':'可信训练验证'}}</h3><p>{{metrics.evaluation_scope==='tuning_oos'?'封存区未参与的 Purged Walk-Forward 结果':'时间线 Purged Walk-Forward 样本外结果'}}</p></div></div><dl class="detail-list"><div><dt><GitBranch :size="15"/>切分方式</dt><dd>{{metrics.split}}</dd></div><div><dt><Database :size="15"/>调参 OOS 样本</dt><dd>{{metrics.test_rows}}</dd></div><div><dt><CalendarDays :size="15"/>Purge / Embargo</dt><dd>{{metrics.purge_days}} / {{metrics.embargo_days}} 交易日</dd></div><div><dt><ShieldCheck :size="15"/>验证折数</dt><dd>{{metrics.folds?.length||0}}</dd></div></dl></article>
        <article class="panel"><div class="panel-head"><div><h3>可复现实验快照</h3><p>定位训练数据、运行环境和模型文件</p></div></div><dl class="detail-list"><div><dt>数据 SHA256</dt><dd><code>{{reproducibility.dataset?.content_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>模型 SHA256</dt><dd><code>{{reproducibility.model_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>样本外预测 SHA256</dt><dd><code>{{reproducibility.prediction_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>Python / sklearn</dt><dd>{{reproducibility.python_version}} / {{reproducibility.sklearn_version}}</dd></div><div><dt>随机种子</dt><dd>{{reproducibility.random_seed}}</dd></div></dl></article>
      </div>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>特征重要性</h3><p>最后调参折上的 permutation importance</p></div><Sparkles :size="18"/></div><div class="artifact" v-for="item in importance" :key="item.feature"><code>{{item.feature}} · {{Number(item.importance_mean).toFixed(6)}} ± {{Number(item.importance_std).toFixed(6)}}</code></div><div v-if="!importance.length" class="empty">该旧模型没有保存解释结果。</div></article>
        <article class="panel"><div class="panel-head"><div><h3>批量推理</h3><p>使用任意兼容特征快照生成可审计 Parquet</p></div></div><button class="primary" @click="router.push('/predictions')"><Sparkles :size="15"/>创建预测任务</button></article>
      </div>
      <article class="panel"><div class="panel-head"><div><h3>各调参折 OOS 结果</h3><p>只用于选择参数，不代表最终封存表现</p></div></div><div class="artifact" v-for="fold in metrics.folds||[]" :key="fold.fold"><code>Fold {{fold.fold}} · {{fold.test_start}} → {{fold.test_end}} · AUC {{fold.roc_auc}} · Balanced Acc {{fold.balanced_accuracy}}</code></div></article>
      <p v-if="error" class="error-box">{{error}}</p>
      <article v-if="user?.role==='admin'" class="panel lifecycle"><div><h3>模型生命周期审批</h3><p>升级、归档与回滚操作都会写入审计日志。</p></div><input v-model="reason" minlength="3"/><div class="row-actions"><button v-if="model.stage==='candidate'" class="primary" :disabled="changing" @click="changeStage('validated')">通过验证</button><button v-if="model.stage==='validated'" class="primary" :disabled="changing" @click="changeStage('production')">发布生产</button><button v-if="model.stage==='archived'" class="primary" :disabled="changing" @click="rollback"><RotateCcw :size="15"/>回滚为生产</button><button v-if="model.stage!=='archived'" class="secondary" :disabled="changing" @click="changeStage('archived')">归档</button></div></article>
    </template>
  </section>
</template>
