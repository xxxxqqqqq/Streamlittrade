<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api'
import {ArrowRight,BrainCircuit,ChartNoAxesCombined,Database,Eye,Plus,RefreshCw} from 'lucide-vue-next'
import SectionTabs from '../components/SectionTabs.vue'
import GuideCard from '../components/GuideCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import VerdictBadge from '../components/VerdictBadge.vue'
import MetricValue from '../components/MetricValue.vue'
import {icDecayVerdict,rankIcVerdict,rocAucVerdict} from '../verdict'
import {trainingTabs} from '../sections'

const router=useRouter()
const experiments=ref<any[]>([]),datasets=ref<any[]>([]),models=ref<any[]>([])
// 最新一次成功实验的模型详情：列表接口只回摘要指标，训练区间与模型没见过的
// 打分区间必须从模型详情里取，所以这里只为最新实验补一次详情请求。
const detail=ref<any>(null)
const loading=ref(false)

// 算法的人话说明：用户不该为了选一个算法去读论文。
const ALGORITHMS:Record<string,string>={
  hist_gradient_boosting:'梯度提升树（推荐：擅长组合弱因子）',
  random_forest:'随机森林（更稳更钝）',
  extra_trees:'极端随机树（横截面增强，波动更大）',
  logistic_regression:'逻辑回归（线性基准线）',
}
function algorithmLabel(value:string){return ALGORITHMS[value]||value||'未记录算法'}
function modelFor(row:any){return models.value.find(item=>item.experiment_id===row.id)}
function datasetFor(row:any){return datasets.value.find(item=>item.id===row.dataset_id)}
function finite(value:any){return typeof value==='number'&&Number.isFinite(value)?value:null}

async function load(){
  loading.value=true
  try{
    const [experimentResponse,datasetResponse,modelResponse]=await Promise.all([api.get('/experiments'),api.get('/datasets'),api.get('/models')])
    experiments.value=experimentResponse.data
    datasets.value=datasetResponse.data
    models.value=modelResponse.data
    const newest=experiments.value.find(row=>modelFor(row))
    detail.value=newest?(await api.get(`/models/${modelFor(newest).id}/detail`)).data:null
  }finally{loading.value=false}
}

interface LearningBrief{factors:number|null;horizon:number|null;training:string|null;unseen:string|null;sealed:string|null}
interface ExperimentCard{row:any;model:any;algorithm:string;brief:LearningBrief;rocAuc:number|null;rankIc:number|null;decay:number|null}

const cards=computed<ExperimentCard[]>(()=>experiments.value.map(row=>{
  const dataset=datasetFor(row),model=modelFor(row)
  const full=model&&detail.value?.id===model.id?detail.value.metrics:{}
  const metrics=full?.roc_auc!==undefined?full:(row.metrics||{})
  const split=metrics.research_split
  const reproducibility=model&&detail.value?.id===model.id?detail.value.reproducibility||{}:{}
  const factorCount=reproducibility.features?.length||(Array.isArray(metrics.feature_importance)&&full?metrics.feature_importance.length:null)||dataset?.feature_count||null
  return {
    row,model,algorithm:algorithmLabel(row.algorithm),
    brief:{
      factors:factorCount,
      horizon:reproducibility.dataset?.horizon??dataset?.specification?.horizon??null,
      training:split?.training?.start?`${split.training.start} ~ ${split.training.end}`:null,
      unseen:split?.tuning?.start?`${split.tuning.start} ~ ${split.tuning.end}`:null,
      sealed:split?.sealed?.start?`${split.sealed.start} ~ ${split.sealed.end}`:null,
    },
    rocAuc:finite(metrics.roc_auc),
    rankIc:finite(metrics.rank_ic),
    decay:finite(metrics.rank_ic_decay),
  }
}))
const datasetCount=computed(()=>datasets.value.length)
const modelCount=computed(()=>models.value.length)
function openModel(card:ExperimentCard){router.push(`/models/${card.model.id}`)}
onMounted(load)
</script>

<template>
  <section>
    <SectionTabs :tabs="trainingTabs" label="训练段页签"/>
    <GuideCard
      :icon="BrainCircuit"
      title="这一步在干什么"
      text="用通过检验的因子，训练一个「预测谁会跑赢大盘」的模型。模型只能用旧数据学习，在它没见过的数据上打分。"
    />

    <div class="model-research-flow">
      <RouterLink to="/datasets" class="research-stage">
        <i>1</i><div class="stage-icon"><Database :size="20"/></div><span><b>准备训练数据</b><small>{{datasetCount}} 个数据集 · 把因子和答案（未来涨跌）对齐后的表格</small></span><ArrowRight :size="16"/>
      </RouterLink>
      <RouterLink to="/experiments/new" class="research-stage active">
        <i>2</i><div class="stage-icon"><BrainCircuit :size="20"/></div><span><b>训练与样本外验证</b><small>{{experiments.length}} 个实验 · 模型在没见过的数据上打分</small></span><ArrowRight :size="16"/>
      </RouterLink>
      <RouterLink to="/models" class="research-stage">
        <i>3</i><div class="stage-icon"><BrainCircuit :size="20"/></div><span><b>审阅候选模型</b><small>{{modelCount}} 个模型版本 · 指标、解释和血缘</small></span><ArrowRight :size="16"/>
      </RouterLink>
    </div>

    <div class="page-intro">
      <div><h2>训练实验</h2><p>每个实验回答两个问题：这次在学什么，学出来的模型好不好。</p></div>
      <div class="experiment-tools">
        <button class="secondary" @click="router.push('/models/compare')"><ChartNoAxesCombined :size="16"/>模型比较</button>
        <button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button>
        <button class="primary" @click="router.push('/experiments/new')"><Plus :size="16"/>新建训练实验</button>
      </div>
    </div>

    <article v-for="card in cards" :key="card.row.id" class="panel experiment-card">
      <div class="experiment-head">
        <div><h3>{{card.row.name}}</h3><p>{{card.algorithm}} · {{datasetFor(card.row)?.name||'数据集已删除'}} · {{new Date(card.row.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}}</p></div>
        <StatusBadge :status="card.row.status"/>
      </div>

      <div class="learning-brief">
        <b>这次训练在学什么</b>
        <p>
          用 <b>{{card.brief.factors??'—'}} 个因子</b>学习预测 <b>{{card.brief.horizon??'—'}} 个交易日后的涨跌</b>。
        </p>
        <p class="learning-ranges">
          <span>学习区间（旧数据）：<b>{{card.brief.training||'完成训练后可查看'}}</b></span>
          <span>打分区间（模型没见过）：<b>{{card.brief.unseen||'见模型详情'}}</b></span>
          <span v-if="card.brief.sealed">终检区间（一次性）：<b>{{card.brief.sealed}}</b></span>
        </p>
      </div>

      <div v-if="card.row.status==='succeeded'" class="result-grid">
        <div class="metric">
          <small>预测能力（ROC AUC）</small>
          <MetricValue :value="card.rocAuc"/>
          <VerdictBadge :verdict="rocAucVerdict(card.rocAuc)"/>
        </div>
        <div class="metric">
          <small>选股区分度（Rank IC）</small>
          <MetricValue :value="card.rankIc" mode="ratio" :digits="3"/>
          <VerdictBadge :verdict="rankIcVerdict(card.rankIc)"/>
        </div>
        <div class="metric">
          <small>信号衰减</small>
          <MetricValue :value="card.decay" mode="ratio" :digits="3"/>
          <VerdictBadge :verdict="icDecayVerdict(card.decay)"/>
        </div>
        <div class="metric">
          <small>成本后收益（研究口径估算）</small>
          <MetricValue :value="card.row.metrics?.cost_adjusted_return" tone/>
          <span class="metric-hint">不是可交易业绩，只是同口径对比用</span>
        </div>
      </div>
      <p v-else-if="card.row.status==='failed'" class="error-box">{{card.row.error_message||'训练失败，原因未记录'}}</p>
      <p v-else class="experiment-waiting">训练进行中：完成后这里会出现预测能力、选股区分度和信号衰减的判断。</p>

      <div class="experiment-actions">
        <span v-if="card.model?.stage==='production'" class="production-hint">该模型已发布生产</span>
        <button v-if="card.model" class="secondary" @click="openModel(card)"><Eye :size="15"/>查看模型详情</button>
        <button v-if="card.model&&card.row.status==='succeeded'" class="primary" @click="router.push({path:'/backtests/new',query:{model_id:card.model.id}})">用这个模型回测</button>
      </div>
    </article>
    <div v-if="!cards.length&&!loading" class="panel empty">还没有训练实验：先准备训练数据，再用通过检验的因子训练第一个模型。</div>
  </section>
</template>

<style scoped>
.model-research-flow{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}.research-stage{display:flex;align-items:center;gap:11px;min-height:86px;padding:15px;border:1px solid #e1e7ef;border-radius:12px;background:#fff;color:#344257;text-decoration:none;box-shadow:0 3px 12px #1f385207}.research-stage>i{width:24px;height:24px;flex:none;border-radius:50%;background:#edf1f6;color:#728096;display:grid;place-items:center;font-size:10px;font-style:normal;font-weight:700}.stage-icon{width:38px;height:38px;flex:none;border-radius:9px;background:#edf5ff;color:#2675d7;display:grid;place-items:center}.research-stage>span{min-width:0;flex:1}.research-stage b,.research-stage small{display:block}.research-stage b{font-size:13px}.research-stage small{margin-top:5px;color:#8a96a6;font-size:10px;line-height:1.4}.research-stage>svg{color:#a1adbb}.research-stage.active{border-color:#c8dafa;background:#f9fbff}.research-stage.active>i{background:#1768d7;color:#fff}
.experiment-tools{display:flex;gap:8px}
.experiment-card{padding:20px 22px;margin-bottom:14px}
.experiment-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}
.experiment-head h3{margin:0;font:700 16px Manrope;color:#1a2233}
.experiment-head p{margin:5px 0 0;color:#8290a2;font-size:11px}
.learning-brief{margin:15px 0;padding:14px 16px;border:1px solid #e3e1fb;border-radius:11px;background:linear-gradient(135deg,#f7f7ff,#fbfaff)}
.learning-brief>b{color:#4f46e5;font-size:12px}
.learning-brief p{margin:6px 0 0;color:#4b5a70;font-size:12px;line-height:1.7}
.learning-brief p>b{color:#1f2b3d}
.learning-ranges{display:flex;flex-wrap:wrap;gap:14px;color:#8290a2!important;font-size:11px!important}
.learning-ranges b{color:#33455c}
.result-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}
.result-grid .metric{display:block;padding:13px 14px;border:1px solid #e6ebf1;border-radius:11px;background:#fafbfd}
.result-grid .metric small{display:block;color:#8290a2;font-size:10px}
.result-grid .metric .metric-value{margin:6px 0;font-size:18px}
.result-grid .metric .verdict-badge{margin-top:2px}
.metric-hint{display:block;margin-top:4px;color:#98a3b2;font-size:9px;line-height:1.5}
.experiment-waiting{margin:0;color:#8290a2;font-size:11px}
.experiment-actions{display:flex;align-items:center;gap:9px;justify-content:flex-end;margin-top:15px}
.production-hint{margin-right:auto;padding:4px 9px;border-radius:99px;background:#e4f8f1;color:#0f7a58;font-size:10px;font-weight:700}
.panel+.panel{margin-top:16px}
@media(max-width:1000px){.model-research-flow{grid-template-columns:1fr}.result-grid{grid-template-columns:1fr 1fr}.page-intro{align-items:flex-start;gap:12px;flex-direction:column}.experiment-tools{flex-wrap:wrap}}
@media(max-width:720px){.result-grid{grid-template-columns:1fr}.experiment-actions{align-items:stretch;flex-direction:column}.experiment-actions .secondary,.experiment-actions .primary{justify-content:center}}
</style>
