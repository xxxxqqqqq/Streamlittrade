<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {api} from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import MetricValue from '../components/MetricValue.vue'
import SectionTabs from '../components/SectionTabs.vue'
import {trainingTabs} from '../sections'
import {statusLabel} from '../status'
import {GitCompareArrows,RefreshCw} from 'lucide-vue-next'
const rows=ref<any[]>([]),selected=ref<string[]>([]),q=ref(''),stage=ref('')
const filtered=computed(()=>rows.value.filter(item=>(!q.value||item.name.toLowerCase().includes(q.value.toLowerCase()))&&(!stage.value||item.stage===stage.value)))
const stages=computed(()=>[...new Set(rows.value.map(item=>item.stage).filter(Boolean))])
const comparison=computed(()=>rows.value.filter(item=>selected.value.includes(item.id)))
// 指标口径与模型详情页保持一致：比例类乘 100 加百分号，比率类保留小数位。
const metricColumns=[
  {key:'roc_auc',label:'ROC AUC',mode:'rate' as const},
  {key:'balanced_accuracy',label:'平衡准确率',mode:'rate' as const},
  {key:'rank_ic',label:'Rank IC',mode:'ratio' as const,digits:3},
  {key:'cost_adjusted_return',label:'成本后收益',mode:'rate' as const,tone:true},
  {key:'annualized_sharpe',label:'年化夏普',mode:'ratio' as const,digits:2},
  {key:'turnover',label:'换手率',mode:'rate' as const},
]
function metric(model:any,key:string){
  const value=model.metrics?.[key]
  return typeof value==='number'&&Number.isFinite(value)?value:null
}
async function load(){rows.value=(await api.get('/models')).data}onMounted(load)
</script>
<template><section><SectionTabs :tabs="trainingTabs" label="训练段页签"/><div class="page-intro"><div><h2>模型横向比较</h2><p>算法、生命周期、样本外经济指标与特征解释并排检查</p></div><button class="secondary" @click="load"><RefreshCw :size="16"/>刷新</button></div><article class="panel"><div class="toolbar"><label><input v-model="q" placeholder="筛选模型名称"/></label><select v-model="stage"><option value="">全部阶段</option><option v-for="value in stages" :key="value" :value="value">{{statusLabel(value)}}</option></select><span>已选择 {{selected.length}} 个</span></div><div class="data-table"><div class="data-row header"><span>选择 / 模型</span><span>算法</span><span>阶段</span><span>ROC AUC</span></div><div v-for="row in filtered" :key="row.id" class="data-row"><span><input v-model="selected" type="checkbox" :value="row.id"/> {{row.name}} v{{row.version}}</span><span>{{row.algorithm}}</span><span><StatusBadge :status="row.stage"/></span><span><MetricValue :value="metric(row,'roc_auc')"/></span></div><div v-if="!filtered.length" class="empty">没有匹配的模型版本。调整筛选条件，或先到“训练实验”完成一次训练。</div></div></article><article v-if="comparison.length" class="panel"><div class="panel-head"><div><h3><GitCompareArrows :size="18"/> 指标矩阵</h3><p>所有值来自样本外预测</p></div></div><div class="compare-matrix"><div class="compare-row"><b>指标</b><strong v-for="model in comparison" :key="model.id">{{model.name}}</strong></div><div v-for="column in metricColumns" :key="column.key" class="compare-row"><b>{{column.label}}</b><span v-for="model in comparison" :key="model.id"><MetricValue :value="metric(model,column.key)" :mode="column.mode" :digits="column.digits" :tone="column.tone"/></span></div><div class="compare-row"><b>Top 特征</b><span v-for="model in comparison" :key="model.id">{{model.metrics?.feature_importance?.slice(0,3).map((item:any)=>item.feature).join('、')||'—'}}</span></div></div></article></section></template>
