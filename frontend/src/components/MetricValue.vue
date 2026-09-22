<script setup lang="ts">
import {computed} from 'vue'

// 指标格式化的唯一实现，三种口径覆盖平台全部指标：
// rate——收益率、概率、换手率等比例值，乘 100 加百分号；
// percent——本身就是百分数的值（回测账本里的 total_return / max_drawdown）；
// ratio——夏普、Rank IC 等纯比率，保留指定小数位。
const props=defineProps<{
  value?:number|string|null
  mode?:'rate'|'percent'|'ratio'
  digits?:number
  tone?:boolean
}>()

const number=computed(()=>{
  if(props.value===null||props.value===undefined||props.value==='')return null
  const parsed=Number(props.value)
  return Number.isFinite(parsed)?parsed:null
})
const text=computed(()=>{
  const current=number.value
  if(current===null)return '—'
  if(props.mode==='ratio')return current.toFixed(props.digits??3)
  if(props.mode==='percent')return `${current.toFixed(props.digits??2)}%`
  return `${(current*100).toFixed(props.digits??2)}%`
})
const toneClass=computed(()=>{
  if(!props.tone||number.value===null)return ''
  if(number.value>0)return 'positive'
  if(number.value<0)return 'negative'
  return ''
})
</script>

<template><span class="metric-value" :class="toneClass">{{text}}</span></template>
