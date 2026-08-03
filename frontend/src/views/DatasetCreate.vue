<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api'
import {ArrowLeft,ArrowRight,CheckCircle2,Database,LoaderCircle} from 'lucide-vue-next'

const router=useRouter()
const form=ref({
  name:'正式特征研究数据集',
  data_source:'feature_snapshot',
  feature_snapshot_id:'',
  symbols:'DEMO',
  start_date:'2018-01-01',
  end_date:'2024-12-31',
  horizon:5,
})
const snapshots=ref<any[]>([])
const submitting=ref(false)
const error=ref('')
const job=ref<any>(null)
const datasetId=ref('')
const progress=computed(()=>job.value?.progress??0)
const formalMode=computed(()=>form.value.data_source==='feature_snapshot')

onMounted(async()=>{
  try{
    snapshots.value=(await api.get('/data-center/materializations')).data.filter(
      (snapshot:any)=>snapshot.status==='ready'
    )
    if(snapshots.value.length)form.value.feature_snapshot_id=snapshots.value[0].id
    else form.value.data_source='demo'
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }
})

async function waitForJob(jobId:string){
  for(let attempt=0;attempt<180;attempt++){
    job.value=(await api.get(`/jobs/${jobId}`)).data
    if(['succeeded','failed'].includes(job.value.status))return
    await new Promise(resolve=>setTimeout(resolve,1000))
  }
  throw new Error('数据集构建超时，请到任务中心查看状态')
}

async function submit(){
  error.value=''
  submitting.value=true
  try{
    const symbols=form.value.symbols.split(/[，,\s]+/).map(value=>value.trim()).filter(Boolean)
    const body={
      ...form.value,
      feature_snapshot_id:formalMode.value?form.value.feature_snapshot_id:null,
      symbols,
      horizon:Number(form.value.horizon),
    }
    const response=await api.post('/datasets',body)
    datasetId.value=response.data.resource_id
    await waitForJob(response.data.job_id)
    if(job.value.status==='failed')throw new Error(job.value.error_message||'数据集构建失败')
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message||'提交失败'
  }finally{
    submitting.value=false
  }
}
</script>

<template>
  <section class="workflow">
    <div class="crumb">
      <button @click="router.push('/datasets')"><ArrowLeft :size="15"/>返回数据集</button>
      <span>研究流程 · 第 1/3 步</span>
    </div>
    <div class="stepper">
      <div class="active"><i>1</i><span>构建数据集</span></div>
      <div><i>2</i><span>训练实验</span></div>
      <div><i>3</i><span>模型结果</span></div>
    </div>
    <article class="panel form-card">
      <div class="form-heading">
        <div class="feature-icon"><Database :size="23"/></div>
        <div>
          <h2>创建研究数据集</h2>
          <p>优先使用已版本化特征快照，标签由同一标准化行情版本计算，完整记录数据血缘。</p>
        </div>
      </div>
      <form v-if="job?.status!=='succeeded'" @submit.prevent="submit">
        <div class="field full">
          <label>数据集名称</label>
          <input v-model="form.name" required minlength="2"/>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>构建方式</label>
            <select v-model="form.data_source">
              <option value="feature_snapshot" :disabled="!snapshots.length">正式特征快照（推荐）</option>
              <option value="demo">演示数据</option>
              <option value="baostock">Baostock 兼容模式</option>
            </select>
          </div>
          <div class="field">
            <label>预测周期（交易日）</label>
            <input v-model.number="form.horizon" type="number" min="1" max="60" required/>
          </div>
          <div v-if="formalMode" class="field full">
            <label>已就绪特征快照</label>
            <select v-model="form.feature_snapshot_id" required>
              <option v-for="snapshot in snapshots" :key="snapshot.id" :value="snapshot.id">
                {{snapshot.name}} · {{snapshot.row_count}}行 · {{snapshot.content_sha256?.slice(0,12)}}
              </option>
            </select>
            <small>训练标签将从该快照绑定的同一标准化行情版本计算。</small>
          </div>
          <template v-else>
            <div class="field full">
              <label>证券代码</label>
              <input v-model="form.symbols" :placeholder="form.data_source==='demo'?'DEMO':'600000, 000001'" required/>
            </div>
            <div class="field"><label>开始日期</label><input v-model="form.start_date" type="date" required/></div>
            <div class="field"><label>结束日期</label><input v-model="form.end_date" type="date" required/></div>
          </template>
        </div>
        <div v-if="job" class="job-progress">
          <div><LoaderCircle :size="17" class="spin"/><span>{{job.status==='queued'?'等待 Worker':'正在合并特征与标签'}}</span><b>{{progress}}%</b></div>
          <div class="progress-track"><i :style="{width:progress+'%'}"></i></div>
        </div>
        <p v-if="error" class="error-box">{{error}}</p>
        <div class="form-actions">
          <button type="button" class="secondary" @click="router.push('/datasets')">取消</button>
          <button class="primary" :disabled="submitting||formalMode&&!form.feature_snapshot_id">
            <LoaderCircle v-if="submitting" :size="16" class="spin"/>
            <Database v-else :size="16"/>
            {{submitting?'正在构建':'构建数据集'}}
          </button>
        </div>
      </form>
      <div v-else class="success-state">
        <CheckCircle2 :size="48"/>
        <h3>数据集已构建完成</h3>
        <p>已生成 {{job.result_summary?.rows}} 行可训练样本，数据版本、特征快照和标签配置已经登记。</p>
        <button class="primary" @click="router.push('/experiments/new?dataset='+datasetId)">
          创建训练实验<ArrowRight :size="16"/>
        </button>
      </div>
    </article>
  </section>
</template>
