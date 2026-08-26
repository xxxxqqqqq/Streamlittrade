<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRouter} from 'vue-router'
import {api} from '../api'
import {pollJobUntilTerminal} from '../jobPolling'
import {ArrowLeft,ArrowRight,CheckCircle2,Database,LoaderCircle} from 'lucide-vue-next'

const router=useRouter()
const form=ref({
  name:'正式特征研究数据集',
  data_source:'feature_snapshot',
  feature_snapshot_id:'',
  factor_research_id:'',
  symbols:'DEMO',
  start_date:'2018-01-01',
  end_date:'2024-12-31',
  horizon:5,
  training_fraction:0.55,
  tuning_fraction:0.25,
  tuning_folds:3,
})
const snapshots=ref<any[]>([])
const factorRuns=ref<any[]>([])
const submitting=ref(false)
const error=ref('')
const job=ref<any>(null)
const datasetId=ref('')
const longRunning=ref(false)
const progress=computed(()=>job.value?.progress??0)
const progressStage=computed(()=>{
  if(job.value?.status==='queued')return '等待本地计算节点接单'
  if(progress.value<14)return '正在校验快照、因子门禁与数据血缘'
  if(progress.value<34)return '正在读取本地缓存中的快照与标准行情'
  if(progress.value<48)return '正在裁剪训练所需因子与可交易股票池'
  if(progress.value<62)return '正在生成未来收益标签并合并特征'
  if(progress.value<80)return '正在清理样本并划分训练、调参与封存区'
  if(progress.value<94)return '正在序列化不可变研究数据集'
  if(progress.value<100)return '正在上传并登记研究数据集'
  return '研究数据集构建完成'
})
const formalMode=computed(()=>form.value.data_source==='feature_snapshot')
const eligibleFactorRuns=computed(()=>factorRuns.value.filter(
  (run:any)=>run.status==='succeeded'
    &&run.metrics?.evaluation_scope==='factor_training_only'
    &&run.selected_feature_slugs?.length>0
))
const selectedFactorRun=computed(()=>eligibleFactorRuns.value.find(
  (run:any)=>run.id===form.value.factor_research_id
))
const selectedSnapshot=computed(()=>snapshots.value.find(
  (snapshot:any)=>snapshot.id===form.value.feature_snapshot_id
))

function applyFactorGate(){
  const run=selectedFactorRun.value
  if(!run)return
  form.value.feature_snapshot_id=run.snapshot_id
  form.value.horizon=Number(run.parameters?.forward_period||form.value.horizon)
  form.value.training_fraction=Number(run.parameters?.training_fraction||form.value.training_fraction)
}

onMounted(async()=>{
  try{
    const [snapshotResponse,researchResponse]=await Promise.all([
      api.get('/data-center/materializations'),
      api.get('/data-center/factor-research'),
    ])
    snapshots.value=snapshotResponse.data.filter(
      (snapshot:any)=>snapshot.status==='ready'
    )
    factorRuns.value=researchResponse.data
    if(eligibleFactorRuns.value.length){
      form.value.factor_research_id=eligibleFactorRuns.value[0].id
      applyFactorGate()
    }
    else form.value.data_source='demo'
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }
})

async function submit(){
  error.value=''
  longRunning.value=false
  submitting.value=true
  try{
    const symbols=form.value.symbols.split(/[，,\s]+/).map(value=>value.trim()).filter(Boolean)
    const body={
      ...form.value,
      feature_snapshot_id:formalMode.value?form.value.feature_snapshot_id:null,
      factor_research_id:formalMode.value?form.value.factor_research_id:null,
      symbols,
      horizon:Number(form.value.horizon),
      training_fraction:Number(form.value.training_fraction),
      tuning_fraction:Number(form.value.tuning_fraction),
      tuning_folds:Number(form.value.tuning_folds),
    }
    const response=await api.post('/datasets',body)
    datasetId.value=response.data.resource_id
    job.value=await pollJobUntilTerminal(
      async()=>(await api.get(`/jobs/${response.data.job_id}`)).data,
      {onUpdate:value=>job.value=value,onLongRunning:()=>longRunning.value=true},
    )
    if(job.value.status!=='succeeded')throw new Error(job.value.error_message||'数据集构建未完成')
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
              <option value="feature_snapshot" :disabled="!eligibleFactorRuns.length">正式特征快照（推荐）</option>
              <option value="demo">演示数据</option>
              <option value="baostock">Baostock 兼容模式</option>
            </select>
          </div>
          <div class="field">
            <label>预测周期（交易日）</label>
            <input v-model.number="form.horizon" type="number" min="1" max="60" required :disabled="formalMode"/>
            <small v-if="formalMode">由因子研究门禁锁定。</small>
          </div>
          <div class="field"><label>训练区比例</label><input v-model.number="form.training_fraction" type="number" min="0.3" max="0.8" step="0.05" required :disabled="formalMode"/><small>{{formalMode?'由因子研究门禁锁定。':'只用于初始拟合。'}}</small></div>
          <div class="field"><label>调参区比例</label><input v-model.number="form.tuning_fraction" type="number" min="0.1" max="0.4" step="0.05" required/><small>Purged Walk-Forward 只在此区比较模型。</small></div>
          <div class="field"><label>调参折数</label><input v-model.number="form.tuning_folds" type="number" min="2" max="6" required/></div>
          <div class="field"><label>最终封存区</label><input :value="`${Math.round((1-form.training_fraction-form.tuning_fraction)*100)}%`" disabled/><small>模型与参数锁定后只允许开启一次。</small></div>
          <div v-if="formalMode" class="field full">
            <label>因子研究门禁</label>
            <select v-model="form.factor_research_id" required @change="applyFactorGate">
              <option v-for="run in eligibleFactorRuns" :key="run.id" :value="run.id">
                {{run.name}} · 通过 {{run.selected_feature_slugs.length}} 个因子 · 未来 {{run.parameters?.forward_period}}日
              </option>
            </select>
            <small>只有研究成功且至少一个因子通过的记录可用；预测周期会自动与研究保持一致。</small>
          </div>
          <div v-if="formalMode" class="field full">
            <label>已就绪特征快照</label>
            <input :value="selectedSnapshot?`${selectedSnapshot.name} · ${selectedSnapshot.row_count}行 · ${selectedSnapshot.content_sha256?.slice(0,12)}`:'等待选择因子门禁'" disabled/>
            <small>快照由因子研究自动绑定；数据集只保留通过门禁的因子，被淘汰因子不会进入训练。</small>
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
          <div><LoaderCircle :size="17" class="spin"/><span>{{progressStage}}</span><b>{{Math.round(progress)}}%</b></div>
          <div class="progress-track"><i :style="{width:progress+'%'}"></i></div>
        </div>
        <div v-if="longRunning" class="background-task-note">
          数据量较大，任务仍在本地计算节点后台运行。可以继续等待，也可以前往
          <button type="button" class="text-button" @click="router.push('/jobs')">任务中心</button>
          查看进度；离开本页不会取消任务。
        </div>
        <p v-if="error" class="error-box">{{error}}</p>
        <div class="form-actions">
          <button type="button" class="secondary" @click="router.push('/datasets')">取消</button>
          <button class="primary" :disabled="submitting||formalMode&&(!form.feature_snapshot_id||!form.factor_research_id)">
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
