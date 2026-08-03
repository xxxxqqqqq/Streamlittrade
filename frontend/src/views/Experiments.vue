<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api'
import {ArrowRight,Boxes,BrainCircuit,ChartNoAxesCombined,Database,Plus,RefreshCw} from 'lucide-vue-next'

const router=useRouter()
const rows=ref<any[]>([])
const datasetCount=ref(0),modelCount=ref(0)
const loading=ref(false)

async function load(){
  loading.value=true
  try{
    const [experiments,datasets,models]=await Promise.all([api.get('/experiments'),api.get('/datasets'),api.get('/models')])
    rows.value=experiments.data;datasetCount.value=datasets.data.length;modelCount.value=models.data.length
  }
  finally{loading.value=false}
}
function metric(row:any,key:string){const value=row.metrics?.[key];return value===undefined||value===null?'—':Number(value).toFixed(4)}
onMounted(load)
</script>

<template>
  <section>
    <div class="page-intro">
      <div><h2>模型研究</h2><p>从不可变训练样本开始，完成训练验证，再审阅候选模型</p></div>
      <button class="primary" @click="router.push('/experiments/new')"><Plus :size="16"/>新建训练实验</button>
    </div>

    <div class="model-research-flow">
      <RouterLink to="/datasets" class="research-stage">
        <i>1</i><div class="stage-icon"><Database :size="20"/></div><span><b>准备训练数据集</b><small>{{datasetCount}} 个数据集 · 固化因子、标签和数据血缘</small></span><ArrowRight :size="16"/>
      </RouterLink>
      <RouterLink to="/experiments/new" class="research-stage active">
        <i>2</i><div class="stage-icon"><BrainCircuit :size="20"/></div><span><b>训练与样本外验证</b><small>{{rows.length}} 个实验 · Purged Walk-Forward</small></span><ArrowRight :size="16"/>
      </RouterLink>
      <RouterLink to="/models" class="research-stage">
        <i>3</i><div class="stage-icon"><Boxes :size="20"/></div><span><b>审阅候选模型</b><small>{{modelCount}} 个模型版本 · 指标、解释和血缘</small></span><ArrowRight :size="16"/>
      </RouterLink>
    </div>

    <article class="panel">
      <div class="toolbar"><span><b>训练实验记录</b><small>比较分析已独立，不影响当前训练主流程</small></span><div class="experiment-tools"><button class="secondary" @click="router.push('/models/compare')"><ChartNoAxesCombined :size="16"/>模型比较</button><button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div></div>
      <div class="data-table">
        <div class="data-row header"><span>实验名称</span><span>算法</span><span>状态</span><span>样本外 ROC AUC</span></div>
        <div v-for="row in rows" :key="row.id" class="data-row">
          <b>{{row.name}}</b><span>{{row.algorithm}}</span><span><i class="status" :class="row.status">{{row.status}}</i></span><span>{{metric(row,'roc_auc')}}</span>
        </div>
        <div v-if="!rows.length&&!loading" class="empty">暂无训练实验，请先准备研究数据集。</div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.model-research-flow{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}.research-stage{display:flex;align-items:center;gap:11px;min-height:86px;padding:15px;border:1px solid #e1e7ef;border-radius:12px;background:#fff;color:#344257;text-decoration:none;box-shadow:0 3px 12px #1f385207}.research-stage>i{width:24px;height:24px;flex:none;border-radius:50%;background:#edf1f6;color:#728096;display:grid;place-items:center;font-size:10px;font-style:normal;font-weight:700}.stage-icon{width:38px;height:38px;flex:none;border-radius:9px;background:#edf5ff;color:#2675d7;display:grid;place-items:center}.research-stage>span{min-width:0;flex:1}.research-stage b,.research-stage small{display:block}.research-stage b{font-size:13px}.research-stage small{margin-top:5px;color:#8a96a6;font-size:10px;line-height:1.4}.research-stage>svg{color:#a1adbb}.research-stage.active{border-color:#c8dafa;background:#f9fbff}.research-stage.active>i{background:#1768d7;color:#fff}.toolbar>span b,.toolbar>span small{display:block}.toolbar>span b{font-size:13px}.toolbar>span small{margin-top:4px;color:#8a96a6;font-size:10px}.experiment-tools{display:flex;gap:8px}.panel+.panel{margin-top:16px}@media(max-width:900px){.model-research-flow{grid-template-columns:1fr}.toolbar{align-items:flex-start;gap:12px;flex-direction:column}.experiment-tools{width:100%}}
</style>
