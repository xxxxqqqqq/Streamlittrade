<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
import {Download,Play,RefreshCw,Sparkles} from 'lucide-vue-next'

const models=ref<any[]>([])
const snapshots=ref<any[]>([])
const rows=ref<any[]>([])
const busy=ref(false)
const error=ref('')
const form=ref({name:'批量因子预测',model_id:'',feature_snapshot_id:''})

async function load(){
  const [modelResponse,snapshotResponse,predictionResponse]=await Promise.all([
    api.get('/models'),api.get('/data-center/materializations'),api.get('/predictions'),
  ])
  models.value=modelResponse.data
  snapshots.value=snapshotResponse.data.filter((item:any)=>item.status==='ready')
  rows.value=predictionResponse.data
  if(!form.value.model_id&&models.value.length)form.value.model_id=models.value[0].id
  if(!form.value.feature_snapshot_id&&snapshots.value.length)form.value.feature_snapshot_id=snapshots.value[0].id
}

async function create(){
  busy.value=true;error.value=''
  try{await api.post('/predictions',form.value);await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}

async function download(row:any){
  const response=await api.get(`/predictions/${row.id}/artifact`,{responseType:'blob'})
  const url=URL.createObjectURL(response.data)
  const link=document.createElement('a');link.href=url;link.download=`prediction-${row.id}.parquet`;link.click()
  URL.revokeObjectURL(url)
}

onMounted(()=>load().catch(exception=>error.value=exception.response?.data?.detail||exception.message))
</script>

<template>
  <section>
    <div class="page-intro">
      <div><h2>批量预测中心</h2><p>注册模型 × 不可变特征快照 → 可审计预测产物</p></div>
      <button class="secondary" @click="load"><RefreshCw :size="16"/>刷新</button>
    </div>
    <p v-if="error" class="error-box">{{error}}</p>
    <article class="panel form-card">
      <div class="form-heading"><div class="feature-icon purple-bg"><Sparkles :size="23"/></div><div><h2>创建预测任务</h2><p>Worker 会检查模型所需特征是否全部存在。</p></div></div>
      <div class="form-grid">
        <div class="field full"><label>任务名称</label><input v-model="form.name"/></div>
        <div class="field"><label>模型版本</label><select v-model="form.model_id"><option v-for="model in models" :key="model.id" :value="model.id">{{model.name}} · {{model.algorithm}} · {{model.stage}}</option></select></div>
        <div class="field"><label>特征快照</label><select v-model="form.feature_snapshot_id"><option v-for="snapshot in snapshots" :key="snapshot.id" :value="snapshot.id">{{snapshot.name}} · {{snapshot.row_count}}行</option></select></div>
      </div>
      <button class="primary" :disabled="busy||!form.model_id||!form.feature_snapshot_id" @click="create"><Play :size="15"/>{{busy?'正在提交':'启动批量预测'}}</button>
    </article>
    <article class="panel">
      <div class="data-table">
        <div class="data-row header with-action"><span>名称</span><span>状态</span><span>行数</span><span>平均概率</span><span>操作</span></div>
        <div v-for="row in rows" :key="row.id" class="data-row with-action">
          <span>{{row.name}}</span><span><i class="status" :class="row.status">{{row.status}}</i></span><span>{{row.row_count||'—'}}</span><span>{{row.summary?.mean_probability??'—'}}</span>
          <span><button v-if="row.status==='succeeded'" class="text-button" @click="download(row)"><Download :size="14"/>下载 Parquet</button></span>
        </div>
        <div v-if="!rows.length" class="empty">暂无预测任务。</div>
      </div>
    </article>
  </section>
</template>
