<script setup lang="ts">
import {computed} from 'vue'
import {RouterLink} from 'vue-router'
import {CheckCircle2,CircleAlert,LoaderCircle} from 'lucide-vue-next'

type Operation='sync'|'materialize'

const props=defineProps<{
  operation:Operation
  status:string
  progress:number
  workerName?:string|null
}>()

const percent=computed(()=>Math.max(0,Math.min(100,Math.round(Number(props.progress)||0))))
const terminal=computed(()=>['succeeded','failed','canceled'].includes(props.status))
const title=computed(()=>props.operation==='materialize'?'正在生成不可变因子快照':'正在同步并标准化行情')
const stage=computed(()=>{
  if(props.status==='queued')return '任务已提交，等待计算节点接单'
  if(props.status==='succeeded')return '数据产物已生成并完成登记'
  if(props.status==='failed')return '任务执行失败，请查看错误信息或前往任务中心重试'
  if(props.status==='canceled')return '任务已取消'
  if(props.operation==='sync'){
    if(percent.value<5)return '正在准备数据源与股票范围'
    if(percent.value<45)return '正在逐只获取并整理行情数据'
    if(percent.value<100)return '正在执行质量门禁、动态股票池与标准化写入'
    return '数据同步完成'
  }
  if(percent.value<10)return '正在读取并校验标准行情'
  if(percent.value<84)return '正在按股票分区计算所选因子'
  if(percent.value<90)return '正在合并因子分区'
  if(percent.value<94)return '正在生成质量摘要与血缘信息'
  if(percent.value<100)return '正在上传并登记不可变快照'
  return '因子快照生成完成'
})
</script>

<template>
  <div class="data-job-progress" aria-live="polite">
    <div class="progress-heading">
      <component
        :is="status==='succeeded'?CheckCircle2:status==='failed'?CircleAlert:LoaderCircle"
        :class="{spin:!terminal}"
        :size="17"
      />
      <b>{{title}}</b>
      <strong>{{percent}}%</strong>
    </div>
    <div
      class="progress-track"
      role="progressbar"
      :aria-label="title"
      :aria-valuenow="percent"
      aria-valuemin="0"
      aria-valuemax="100"
    ><i :style="{width:`${percent}%`}"></i></div>
    <div class="progress-detail">
      <span>{{stage}}</span>
      <small>{{workerName?`计算节点：${workerName}`:'进度会自动更新，离开本页不会取消任务'}}</small>
      <RouterLink to="/jobs">任务中心</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.data-job-progress{margin:13px 0;padding:13px 14px;border:1px solid #cfe0f4;border-radius:9px;background:#f4f9ff;color:#31506f}
.progress-heading{display:flex;align-items:center;gap:8px;font-size:11px}.progress-heading>svg{color:#1768d7}.progress-heading strong{margin-left:auto;color:#1768d7;font-size:12px}
.progress-track{height:7px;margin:10px 0 8px;overflow:hidden;border-radius:7px;background:#dce8f5}.progress-track i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#2478df,#27b99f);transition:width .35s ease}
.progress-detail{display:flex;align-items:center;gap:10px;font-size:10px}.progress-detail span{font-weight:700}.progress-detail small{margin-left:auto;color:#7b8999}.progress-detail a{color:#1768d7;font-weight:700;text-decoration:none;white-space:nowrap}
@media(max-width:720px){.progress-detail{align-items:flex-start;flex-direction:column}.progress-detail small{margin-left:0}}
</style>
