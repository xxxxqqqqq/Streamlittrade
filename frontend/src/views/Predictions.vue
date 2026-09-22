<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute} from 'vue-router'
import {api} from '../api'
import {pollJobUntilTerminal} from '../jobPolling'
import StatusBadge from '../components/StatusBadge.vue'
import {Download,LoaderCircle,Play,RefreshCw,Sparkles} from 'lucide-vue-next'

const route=useRoute()
const models=ref<any[]>([])
const snapshots=ref<any[]>([])
const rows=ref<any[]>([])
const busy=ref(false)
const error=ref('')
const notice=ref('')
const job=ref<any>(null)
const longRunning=ref(false)
const form=ref({name:'批量因子预测',model_id:'',feature_snapshot_id:''})

const progressStage=computed(()=>{
  if(job.value?.status==='queued')return '等待本地计算节点接单'
  const progress=Number(job.value?.progress||0)
  if(progress<30)return '正在校验模型与特征快照的兼容性'
  if(progress<70)return '正在计算横截面概率与排名'
  if(progress<100)return '正在序列化并上传预测产物'
  return '预测产物已登记'
})

async function load(){
  try{
    const [modelResponse,snapshotResponse,predictionResponse]=await Promise.all([
      api.get('/models'),api.get('/data-center/materializations'),api.get('/predictions'),
    ])
    // 只有产出过样本外预测的模型才能直接批量推理；列出其他模型只会让用户
    // 提交一个必然失败的任务。
    models.value=modelResponse.data.filter((item:any)=>Boolean(item.prediction_artifact_uri))
    snapshots.value=snapshotResponse.data.filter((item:any)=>item.status==='ready')
    rows.value=predictionResponse.data
    const requested=String(route.query.model_id||'')||form.value.model_id
    form.value.model_id=models.value.some((item:any)=>item.id===requested)?requested:(models.value[0]?.id||'')
    if(!form.value.feature_snapshot_id&&snapshots.value.length)form.value.feature_snapshot_id=snapshots.value[0].id
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
}

async function create(){
  busy.value=true;error.value='';notice.value='';longRunning.value=false
  try{
    const response=await api.post('/predictions',form.value)
    job.value=await pollJobUntilTerminal(
      async()=>(await api.get(`/jobs/${response.data.job_id}`)).data,
      {onUpdate:value=>job.value=value,onLongRunning:()=>longRunning.value=true},
    )
    if(job.value.status!=='succeeded')throw new Error(job.value.error_message||'批量预测未完成')
    await load()
    notice.value='预测产物已登记，可在下方列表中下载 Parquet。'
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}

async function download(row:any){
  const response=await api.get(`/predictions/${row.id}/artifact`,{responseType:'blob'})
  const url=URL.createObjectURL(response.data)
  const link=document.createElement('a');link.href=url;link.download=`prediction-${row.id}.parquet`;link.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-intro">
      <div><h2>批量预测中心</h2><p>注册模型 × 不可变特征快照 → 可审计预测产物</p></div>
      <button class="secondary" @click="load"><RefreshCw :size="16"/>刷新</button>
    </div>
    <p v-if="error" class="error-box">{{error}}</p>
    <p v-if="notice" class="notice-box">{{notice}}</p>
    <article class="panel form-card">
      <div class="form-heading"><div class="feature-icon purple-bg"><Sparkles :size="23"/></div><div><h2>创建预测任务</h2><p>Worker 会检查模型所需特征是否全部存在。</p></div></div>
      <div class="form-grid">
        <div class="field full"><label>任务名称</label><input v-model="form.name"/></div>
        <div class="field"><label>模型版本</label><select v-model="form.model_id"><option v-for="model in models" :key="model.id" :value="model.id">{{model.name}} · {{model.algorithm}} · {{model.stage}}</option></select><small>{{models.length?'只列出已具备样本外预测产物的模型。':'当前项目还没有可批量推理的模型，请先完成训练实验。'}}</small></div>
        <div class="field"><label>特征快照</label><select v-model="form.feature_snapshot_id"><option v-for="snapshot in snapshots" :key="snapshot.id" :value="snapshot.id">{{snapshot.name}} · {{snapshot.row_count}}行</option></select></div>
      </div>
      <div v-if="job" class="job-progress">
        <div><LoaderCircle :size="17" class="spin"/><span>{{progressStage}}</span><b>{{Math.round(Number(job.progress||0))}}%</b></div>
        <div class="progress-track"><i :style="{width:job.progress+'%'}"></i></div>
      </div>
      <div v-if="longRunning" class="background-task-note">预测仍在后台运行。可以继续等待，或前往 <RouterLink to="/jobs">任务中心</RouterLink> 查看进度；离开本页不会取消任务。</div>
      <button class="primary" :disabled="busy||!form.model_id||!form.feature_snapshot_id" @click="create"><Play :size="15"/>{{busy?'正在预测':'启动批量预测'}}</button>
    </article>
    <article class="panel">
      <div class="data-table">
        <div class="data-row header with-action"><span>名称</span><span>状态</span><span>行数</span><span>平均概率</span><span>操作</span></div>
        <div v-for="row in rows" :key="row.id" class="data-row with-action">
          <span>{{row.name}}</span><span><StatusBadge :status="row.status"/></span><span>{{row.row_count||'—'}}</span><span>{{row.summary?.mean_probability??'—'}}</span>
          <span><button v-if="row.status==='succeeded'" class="text-button" @click="download(row)"><Download :size="14"/>下载 Parquet</button></span>
        </div>
        <div v-if="!rows.length" class="empty">暂无预测任务。</div>
      </div>
    </article>
  </section>
</template>
