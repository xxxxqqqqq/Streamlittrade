<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {ArrowLeft,ArrowRight,BrainCircuit,CheckCircle2,LoaderCircle} from 'lucide-vue-next'

const route=useRoute(),router=useRouter()
const datasets=ref<any[]>([])
const job=ref<any>(null),error=ref(''),submitting=ref(false),modelId=ref('')
const form=ref({
  name:'多算法基线实验',
  dataset_id:String(route.query.dataset||''),
  algorithm:'hist_gradient_boosting',
  max_iter:150,max_depth:5,learning_rate:0.05,
  n_estimators:300,min_samples_leaf:5,
  C:1.0,
})
const readyDatasets=computed(()=>datasets.value.filter(item=>item.status==='ready'))

onMounted(async()=>{
  datasets.value=(await api.get('/datasets')).data
  if(!form.value.dataset_id&&readyDatasets.value.length)form.value.dataset_id=readyDatasets.value[0].id
})

async function waitForJob(jobId:string){
  for(let index=0;index<300;index++){
    job.value=(await api.get(`/jobs/${jobId}`)).data
    if(['succeeded','failed'].includes(job.value.status))return
    await new Promise(resolve=>setTimeout(resolve,1000))
  }
  throw new Error('模型训练超时，请到任务中心查看状态')
}

async function submit(){
  error.value='';submitting.value=true
  try{
    const parameters=form.value.algorithm==='hist_gradient_boosting'
      ? {max_iter:Number(form.value.max_iter),max_depth:Number(form.value.max_depth),learning_rate:Number(form.value.learning_rate)}
      : form.value.algorithm==='random_forest'
        ? {n_estimators:Number(form.value.n_estimators),max_depth:Number(form.value.max_depth),min_samples_leaf:Number(form.value.min_samples_leaf)}
        : {C:Number(form.value.C),max_iter:Number(form.value.max_iter)}
    const response=await api.post('/experiments',{
      name:form.value.name,dataset_id:form.value.dataset_id,
      algorithm:form.value.algorithm,parameters,
    })
    await waitForJob(response.data.job_id)
    if(job.value.status==='failed')throw new Error(job.value.error_message||'训练失败')
    modelId.value=job.value.result_summary.model_id
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message||'提交失败'}
  finally{submitting.value=false}
}
</script>

<template>
  <section class="workflow">
    <div class="crumb"><button @click="router.push('/experiments')"><ArrowLeft :size="15"/>返回实验</button><span>研究流程 · 第 2/3 步</span></div>
    <div class="stepper"><div class="done"><i>✓</i><span>构建数据集</span></div><div class="active"><i>2</i><span>训练实验</span></div><div><i>3</i><span>模型结果</span></div></div>
    <article class="panel form-card">
      <div class="form-heading"><div class="feature-icon purple-bg"><BrainCircuit :size="23"/></div><div><h2>创建训练实验</h2><p>三种算法使用相同的时间隔离验证与经济指标，可在实验中心横向比较。</p></div></div>
      <form v-if="job?.status!=='succeeded'" @submit.prevent="submit">
        <div class="field full"><label>实验名称</label><input v-model="form.name" required minlength="2"/></div>
        <div class="field full"><label>已就绪数据集</label><select v-model="form.dataset_id" required><option disabled value="">请选择数据集</option><option v-for="item in readyDatasets" :key="item.id" :value="item.id">{{item.name}} · {{item.row_count}} 行</option></select></div>
        <div class="form-grid">
          <div class="field full"><label>算法</label><select v-model="form.algorithm"><option value="hist_gradient_boosting">Histogram Gradient Boosting</option><option value="random_forest">Random Forest</option><option value="logistic_regression">Logistic Regression</option></select></div>
          <template v-if="form.algorithm==='hist_gradient_boosting'">
            <div class="field"><label>最大迭代次数</label><input v-model.number="form.max_iter" type="number" min="10"/></div>
            <div class="field"><label>树最大深度</label><input v-model.number="form.max_depth" type="number" min="1"/></div>
            <div class="field"><label>学习率</label><input v-model.number="form.learning_rate" type="number" min="0.001" step="0.001"/></div>
          </template>
          <template v-else-if="form.algorithm==='random_forest'">
            <div class="field"><label>树数量</label><input v-model.number="form.n_estimators" type="number" min="10"/></div>
            <div class="field"><label>树最大深度</label><input v-model.number="form.max_depth" type="number" min="1"/></div>
            <div class="field"><label>叶节点最小样本</label><input v-model.number="form.min_samples_leaf" type="number" min="1"/></div>
          </template>
          <template v-else>
            <div class="field"><label>正则强度 C</label><input v-model.number="form.C" type="number" min="0.001" step="0.1"/></div>
            <div class="field"><label>最大迭代次数</label><input v-model.number="form.max_iter" type="number" min="10"/></div>
          </template>
        </div>
        <div v-if="job" class="job-progress"><div><LoaderCircle :size="17" class="spin"/><span>{{job.status==='queued'?'等待训练资源':'正在训练、解释和评估模型'}}</span><b>{{job.progress}}%</b></div><div class="progress-track"><i :style="{width:job.progress+'%'}"></i></div></div>
        <p v-if="error" class="error-box">{{error}}</p>
        <div class="form-actions"><button type="button" class="secondary" @click="router.push('/experiments')">取消</button><button class="primary" :disabled="submitting||!readyDatasets.length"><LoaderCircle v-if="submitting" :size="16" class="spin"/><BrainCircuit v-else :size="16"/>{{submitting?'正在训练':'开始训练'}}</button></div>
      </form>
      <div v-else class="success-state"><CheckCircle2 :size="48"/><h3>训练、解释与模型登记完成</h3><p>模型及样本外预测已经保存，可以进入模型仓库审批或创建批量预测。</p><button class="primary" @click="router.push('/models/'+modelId)">查看模型结果<ArrowRight :size="16"/></button></div>
    </article>
  </section>
</template>
