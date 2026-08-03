<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {api,rootApi} from '../api'
import {
  Activity,AlertTriangle,CheckCircle2,Clock3,Database,Play,
  RefreshCw,ShieldAlert,SlidersHorizontal,
} from 'lucide-vue-next'

const overview=ref<any>(null),health=ref<any>(null),loading=ref(false),busy=ref(false),error=ref('')
const schedules=ref<any[]>([]),driftRuns=ref<any[]>([]),alerts=ref<any[]>([])
const models=ref<any[]>([]),snapshots=ref<any[]>([])
const scheduleForm=ref({name:'每日生产预测',algorithm:'random_forest',feature_snapshot_id:'',interval_minutes:1440})
const driftForm=ref({model_id:'',current_snapshot_id:''})
let timer:number|undefined

const productionModels=computed(()=>models.value.filter(model=>model.stage==='production'))
const readySnapshots=computed(()=>snapshots.value.filter(snapshot=>snapshot.status==='ready'))

async function load(){
  loading.value=true
  try{
    const [overviewResponse,readyResponse,scheduleResponse,driftResponse,alertResponse,modelResponse,snapshotResponse]=await Promise.all([
      api.get('/monitoring/overview'),rootApi.get('/health/ready'),
      api.get('/prediction-schedules'),api.get('/monitoring/drift-runs'),
      api.get('/monitoring/alerts'),api.get('/models'),api.get('/data-center/materializations'),
    ])
    overview.value=overviewResponse.data;health.value=readyResponse.data
    schedules.value=scheduleResponse.data;driftRuns.value=driftResponse.data;alerts.value=alertResponse.data
    models.value=modelResponse.data;snapshots.value=snapshotResponse.data
    if(!scheduleForm.value.feature_snapshot_id&&readySnapshots.value.length)scheduleForm.value.feature_snapshot_id=readySnapshots.value[0].id
    if(!driftForm.value.current_snapshot_id&&readySnapshots.value.length)driftForm.value.current_snapshot_id=readySnapshots.value[0].id
    if(!driftForm.value.model_id&&productionModels.value.length)driftForm.value.model_id=productionModels.value[0].id
    if(productionModels.value.length&&!productionModels.value.some(model=>model.algorithm===scheduleForm.value.algorithm)){
      scheduleForm.value.algorithm=productionModels.value[0].algorithm
    }
  }catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{loading.value=false}
}

async function createSchedule(){
  busy.value=true;error.value=''
  try{await api.post('/prediction-schedules',{...scheduleForm.value,interval_minutes:Number(scheduleForm.value.interval_minutes)});await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}
async function runSchedule(item:any){
  busy.value=true;error.value=''
  try{await api.post(`/prediction-schedules/${item.id}/run`);await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}
async function toggleSchedule(item:any){
  busy.value=true;error.value=''
  try{await api.patch(`/prediction-schedules/${item.id}`,{enabled:!item.enabled});await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}
async function createDriftRun(){
  busy.value=true;error.value=''
  try{await api.post('/monitoring/drift-runs',driftForm.value);await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}
async function updateAlert(item:any,status:string){
  busy.value=true;error.value=''
  try{await api.patch(`/monitoring/alerts/${item.id}`,{status});await load()}
  catch(exception:any){error.value=exception.response?.data?.detail||exception.message}
  finally{busy.value=false}
}
function time(value:string|null){return value?new Date(value).toLocaleString():'—'}

onMounted(()=>{load();timer=window.setInterval(load,10000)})
onUnmounted(()=>window.clearInterval(timer))
</script>

<template>
  <section>
    <div class="page-intro">
      <div><h2>生产运行中心</h2><p>自动预测、模型漂移、告警处置与基础设施状态</p></div>
      <button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button>
    </div>
    <p v-if="error" class="error-box">{{error}}</p>
    <div v-if="overview" class="monitor-grid">
      <article class="monitor-card"><Activity/><div><small>运行中任务</small><strong>{{overview.jobs.running||0}}</strong></div></article>
      <article class="monitor-card"><Clock3/><div><small>启用预测计划</small><strong>{{overview.enabled_schedules||0}}</strong></div></article>
      <article class="monitor-card"><Database/><div><small>生产模型</small><strong>{{overview.models.production||0}}</strong></div></article>
      <article class="monitor-card"><ShieldAlert/><div><small>未处置告警</small><strong>{{overview.open_alerts||0}}</strong></div></article>
      <article class="monitor-card healthy"><CheckCircle2/><div><small>基础设施</small><strong>{{health?.status||'unknown'}}</strong></div></article>
    </div>

    <div class="detail-grid operations-grid">
      <article class="panel">
        <div class="panel-head"><div><h3>自动预测计划</h3><p>始终调用所选算法当前的生产模型</p></div><Clock3 :size="19"/></div>
        <div class="field"><label>计划名称</label><input v-model="scheduleForm.name"/></div>
        <div class="field"><label>生产算法</label><select v-model="scheduleForm.algorithm"><option v-for="model in productionModels" :key="model.algorithm" :value="model.algorithm">{{model.algorithm}}</option></select></div>
        <div class="field"><label>特征快照</label><select v-model="scheduleForm.feature_snapshot_id"><option v-for="snapshot in readySnapshots" :key="snapshot.id" :value="snapshot.id">{{snapshot.name}} · {{snapshot.row_count}} 行</option></select></div>
        <div class="field"><label>运行间隔（分钟）</label><input v-model.number="scheduleForm.interval_minutes" type="number" min="5" max="10080"/></div>
        <button class="primary" :disabled="busy||!productionModels.length||!scheduleForm.feature_snapshot_id" @click="createSchedule"><Clock3 :size="15"/>创建计划</button>
      </article>
      <article class="panel">
        <div class="panel-head"><div><h3>模型漂移检查</h3><p>训练基线快照与当前快照的 PSI 和预测分数偏移</p></div><SlidersHorizontal :size="19"/></div>
        <div class="field"><label>模型版本</label><select v-model="driftForm.model_id"><option v-for="model in models" :key="model.id" :value="model.id">{{model.name}} · {{model.algorithm}} · {{model.stage}}</option></select></div>
        <div class="field"><label>当前特征快照</label><select v-model="driftForm.current_snapshot_id"><option v-for="snapshot in readySnapshots" :key="snapshot.id" :value="snapshot.id">{{snapshot.name}} · {{snapshot.content_sha256?.slice(0,10)}}</option></select></div>
        <button class="primary" :disabled="busy||!driftForm.model_id||!driftForm.current_snapshot_id" @click="createDriftRun"><Play :size="15"/>开始漂移检查</button>
      </article>
    </div>

    <article class="panel">
      <div class="panel-head"><div><h3>预测计划</h3><p>数据库保存下一执行时间，服务重启后继续运行</p></div></div>
      <div class="data-table">
        <div class="data-row header with-action"><span>计划 / 算法</span><span>状态</span><span>下次运行</span><span>上次任务</span><span>操作</span></div>
        <div v-for="item in schedules" :key="item.id" class="data-row with-action">
          <span>{{item.name}}<small>{{item.algorithm}} · 每 {{item.interval_minutes}} 分钟</small></span>
          <span><i class="status" :class="item.enabled?'succeeded':'archived'">{{item.enabled?'enabled':'paused'}}</i></span>
          <span>{{time(item.next_run_at)}}</span><span><code>{{item.last_job_id?.slice(0,8)||'—'}}</code></span>
          <span class="row-actions"><button class="text-button" :disabled="busy" @click="runSchedule(item)">立即运行</button><button class="text-button" :disabled="busy" @click="toggleSchedule(item)">{{item.enabled?'暂停':'启用'}}</button></span>
        </div>
        <div v-if="!schedules.length" class="empty">尚未创建自动预测计划。</div>
      </div>
    </article>

    <article class="panel">
      <div class="panel-head"><div><h3>漂移检查记录</h3><p>PSI ≥ 0.10 为 warning，PSI ≥ 0.25 为 critical</p></div></div>
      <div class="data-table">
        <div class="data-row header"><span>时间 / 状态</span><span>告警级别</span><span>最大特征 PSI</span><span>预测分数 PSI</span></div>
        <div v-for="item in driftRuns" :key="item.id" class="data-row">
          <span>{{time(item.created_at)}}<small>{{item.status}}</small></span>
          <span><i class="status" :class="item.alert_level">{{item.alert_level}}</i></span>
          <span>{{item.metrics?.max_feature_psi??'—'}}</span><span>{{item.metrics?.score_psi??'—'}}</span>
        </div>
        <div v-if="!driftRuns.length" class="empty">暂无漂移检查。</div>
      </div>
    </article>

    <article class="panel alert-panel">
      <div class="panel-head"><div><h3>持久化生产告警</h3><p>确认和解决操作会记录操作者与审计日志</p></div><span>{{overview?time(overview.generated_at):''}}</span></div>
      <div v-if="!alerts.length" class="all-clear"><CheckCircle2 :size="24"/><div><b>当前没有生产告警</b><small>模型输入和自动任务状态正常</small></div></div>
      <div class="alert-item operational-alert" v-for="item in alerts" :key="item.id" :class="item.severity">
        <AlertTriangle :size="18"/><div><b>{{item.title}} · {{item.status}}</b><span>{{item.message}} · {{time(item.created_at)}}</span></div>
        <div v-if="item.status!=='resolved'" class="row-actions"><button v-if="item.status==='open'" class="text-button" :disabled="busy" @click="updateAlert(item,'acknowledged')">确认</button><button class="text-button" :disabled="busy" @click="updateAlert(item,'resolved')">解决</button></div>
      </div>
    </article>

    <article v-if="overview?.alerts?.length" class="panel alert-panel">
      <div class="panel-head"><div><h3>即时平台状态</h3><p>从当前任务和资源状态动态汇总</p></div></div>
      <div class="alert-item" v-for="item in overview.alerts" :key="item.code" :class="item.severity"><AlertTriangle :size="18"/><div><b>{{item.code}}</b><span>{{item.message}}</span></div></div>
    </article>
  </section>
</template>
