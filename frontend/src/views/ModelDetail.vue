<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {user} from '../auth'
import {ArrowLeft,Boxes,CalendarDays,Database,GitBranch,RotateCcw,ShieldCheck,Sparkles} from 'lucide-vue-next'

const route=useRoute(),router=useRouter(),model=ref<any>(null),loading=ref(true),error=ref('')
const reason=ref('已检查样本外指标、时间隔离和经济指标'),changing=ref(false)
onMounted(async()=>{
  try{
    const models=(await api.get('/models')).data
    model.value=models.find((item:any)=>item.id===route.params.id)
    if(!model.value)error.value='没有找到该模型版本'
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{loading.value=false}
})
const metrics=computed(()=>model.value?.metrics||{})
const reproducibility=computed(()=>model.value?.reproducibility||{})
const importance=computed(()=>metrics.value.feature_importance||[])
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
</script>

<template>
  <section class="workflow">
    <div class="crumb"><button @click="router.push('/models')"><ArrowLeft :size="15"/>返回模型仓库</button><span>研究流程 · 第 3/3 步</span></div>
    <div v-if="loading" class="panel empty">正在读取模型结果…</div>
    <div v-else-if="error&&!model" class="panel error-box">{{error}}</div>
    <template v-else>
      <article class="model-hero"><div class="feature-icon purple-bg"><Boxes :size="25"/></div><div><span class="eyebrow dark">REGISTERED MODEL</span><h2>{{model.name}}</h2><p>{{model.algorithm}} · Version {{model.version}}</p></div><i class="status" :class="model.stage">{{model.stage}}</i></article>
      <div class="result-grid"><article class="panel metric-result" v-for="[label,value,type] in metricCards" :key="String(label)"><small>{{label}}</small><strong>{{display(value,String(type))}}</strong></article></div>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>可信训练验证</h3><p>时间线 Purged Walk-Forward 样本外结果</p></div></div><dl class="detail-list"><div><dt><GitBranch :size="15"/>切分方式</dt><dd>{{metrics.split}}</dd></div><div><dt><Database :size="15"/>样本外样本</dt><dd>{{metrics.test_rows}}</dd></div><div><dt><CalendarDays :size="15"/>Purge / Embargo</dt><dd>{{metrics.purge_days}} / {{metrics.embargo_days}} 交易日</dd></div><div><dt><ShieldCheck :size="15"/>验证折数</dt><dd>{{metrics.folds?.length||0}}</dd></div></dl></article>
        <article class="panel"><div class="panel-head"><div><h3>可复现实验快照</h3><p>定位训练数据、运行环境和模型文件</p></div></div><dl class="detail-list"><div><dt>数据 SHA256</dt><dd><code>{{reproducibility.dataset?.content_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>模型 SHA256</dt><dd><code>{{reproducibility.model_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>样本外预测 SHA256</dt><dd><code>{{reproducibility.prediction_sha256?.slice(0,20)||'—'}}…</code></dd></div><div><dt>Python / sklearn</dt><dd>{{reproducibility.python_version}} / {{reproducibility.sklearn_version}}</dd></div><div><dt>随机种子</dt><dd>{{reproducibility.random_seed}}</dd></div></dl></article>
      </div>
      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>特征重要性</h3><p>最终样本外折上的 permutation importance</p></div><Sparkles :size="18"/></div><div class="artifact" v-for="item in importance" :key="item.feature"><code>{{item.feature}} · {{Number(item.importance_mean).toFixed(6)}} ± {{Number(item.importance_std).toFixed(6)}}</code></div><div v-if="!importance.length" class="empty">该旧模型没有保存解释结果。</div></article>
        <article class="panel"><div class="panel-head"><div><h3>批量推理</h3><p>使用任意兼容特征快照生成可审计 Parquet</p></div></div><button class="primary" @click="router.push('/predictions')"><Sparkles :size="15"/>创建预测任务</button></article>
      </div>
      <article class="panel"><div class="panel-head"><div><h3>各折样本外结果</h3><p>检查指标是否只由个别时期贡献</p></div></div><div class="artifact" v-for="fold in metrics.folds||[]" :key="fold.fold"><code>Fold {{fold.fold}} · {{fold.test_start}} → {{fold.test_end}} · AUC {{fold.roc_auc}} · Balanced Acc {{fold.balanced_accuracy}}</code></div></article>
      <p v-if="error" class="error-box">{{error}}</p>
      <article v-if="user?.role==='admin'" class="panel lifecycle"><div><h3>模型生命周期审批</h3><p>升级、归档与回滚操作都会写入审计日志。</p></div><input v-model="reason" minlength="3"/><div class="row-actions"><button v-if="model.stage==='candidate'" class="primary" :disabled="changing" @click="changeStage('validated')">通过验证</button><button v-if="model.stage==='validated'" class="primary" :disabled="changing" @click="changeStage('production')">发布生产</button><button v-if="model.stage==='archived'" class="primary" :disabled="changing" @click="rollback"><RotateCcw :size="15"/>回滚为生产</button><button v-if="model.stage!=='archived'" class="secondary" :disabled="changing" @click="changeStage('archived')">归档</button></div></article>
    </template>
  </section>
</template>
