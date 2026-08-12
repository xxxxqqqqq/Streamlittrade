<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute} from 'vue-router'
import {Activity,CheckCircle2,Filter,FlaskConical,RefreshCw,XCircle} from 'lucide-vue-next'
import {api} from '../api'

const route=useRoute()

const snapshots=ref<any[]>([])
const runs=ref<any[]>([])
const selectedRunId=ref('')
const busy=ref(false)
const error=ref('')
const notice=ref('')
const form=ref({
  name:'5日收益因子研究',
  snapshot_id:'',
  forward_period:5,
  training_fraction:.55,
  quantiles:5,
  min_coverage:.7,
  min_abs_rank_ic:.02,
  min_ic_ir:.2,
  false_discovery_rate:.05,
  min_ic_observations:30,
})

const selectedRun=computed(()=>runs.value.find(item=>item.id===selectedRunId.value))
const factorRows=computed(()=>Object.entries(selectedRun.value?.metrics?.factors||{}).map(([slug,metrics])=>({slug,...metrics as any})))
const factorSlugs=computed(()=>factorRows.value.map(item=>item.slug))

function percent(value:any){
  return value===null||value===undefined?'—':`${(Number(value)*100).toFixed(2)}%`
}
function number(value:any,digits=4){
  return value===null||value===undefined?'—':Number(value).toFixed(digits)
}
function correlation(left:string,right:string){
  return selectedRun.value?.metrics?.correlation?.[left]?.[right]
}
function correlationColor(value:any){
  if(value===null||value===undefined)return{}
  const strength=Math.min(.85,Math.abs(Number(value)))
  return {
    background:Number(value)>=0?`rgba(23,104,215,${.08+strength*.45})`:`rgba(220,72,72,${.08+strength*.4})`,
    color:strength>.55?'#fff':'#35445a',
  }
}

async function load(){
  const [snapshotResponse,runResponse]=await Promise.all([
    api.get('/data-center/materializations'),
    api.get('/data-center/factor-research'),
  ])
  snapshots.value=snapshotResponse.data.filter((item:any)=>item.status==='ready')
  runs.value=runResponse.data
  const requestedSnapshot=String(route.query.snapshot||'')
  if(snapshots.value.some((item:any)=>item.id===requestedSnapshot))form.value.snapshot_id=requestedSnapshot
  else if(!form.value.snapshot_id&&snapshots.value.length)form.value.snapshot_id=snapshots.value[0].id
  if(!runs.value.some(item=>item.id===selectedRunId.value)&&runs.value.length)selectedRunId.value=runs.value[0].id
}

async function wait(jobId:string){
  for(let index=0;index<300;index++){
    const job=(await api.get(`/jobs/${jobId}`)).data
    if(['succeeded','failed','canceled'].includes(job.status)){
      if(job.status!=='succeeded')throw new Error(job.error_message||'因子研究任务失败')
      return
    }
    await new Promise(resolve=>setTimeout(resolve,1000))
  }
  throw new Error('因子研究任务超时')
}

async function createResearch(){
  busy.value=true;error.value='';notice.value=''
  try{
    const response=await api.post('/data-center/factor-research',form.value)
    await wait(response.data.job_id)
    await load()
    selectedRunId.value=response.data.resource_id
    notice.value='因子研究完成，筛选结论已保存。'
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{busy.value=false}
}

onMounted(()=>load().catch(exception=>error.value=exception.response?.data?.detail||exception.message))
</script>

<template>
  <section>
    <div class="hero factor-hero">
      <div>
        <span class="eyebrow">FACTOR RESEARCH & SCREENING</span>
        <h2>因子研究与筛选</h2>
        <p>使用未来收益检验因子的覆盖率、IC稳定性、分层收益、换手率与相关性，筛选后再进入建模。</p>
      </div>
      <Filter :size="52"/>
    </div>

    <p v-if="error" class="error-box">{{error}}</p>
    <p v-if="notice" class="research-notice"><CheckCircle2 :size="16"/>{{notice}}</p>

    <article class="panel research-create">
      <div class="panel-head">
        <div><h3>发起因子检验</h3><p>一个研究任务绑定一个不可变因子快照，结果可以重复审计。</p></div>
        <FlaskConical :size="22"/>
      </div>
      <div class="research-form">
        <div class="field"><label>研究名称</label><input v-model="form.name"/></div>
        <div class="field snapshot-field">
          <label>不可变因子快照</label>
          <select v-model="form.snapshot_id">
            <option disabled value="">请先在数据中心生成快照</option>
            <option v-for="snapshot in snapshots" :key="snapshot.id" :value="snapshot.id">
              {{snapshot.name}} · {{snapshot.row_count}}行 · {{snapshot.feature_definition_ids.length}}因子
            </option>
          </select>
        </div>
        <div class="field"><label>预测周期（交易日）</label><input v-model.number="form.forward_period" type="number" min="1" max="60"/></div>
        <div class="field"><label title="因子仅使用训练区数据筛选，调参区和最终封存区不会参与本步骤。">训练区比例</label><input v-model.number="form.training_fraction" type="number" min=".3" max=".8" step=".05"/></div>
        <div class="field"><label>分层数量</label><input v-model.number="form.quantiles" type="number" min="2" max="10"/></div>
        <div class="field"><label>最低覆盖率</label><input v-model.number="form.min_coverage" type="number" min="0" max="1" step=".05"/></div>
        <div class="field"><label>最低 |Rank IC|</label><input v-model.number="form.min_abs_rank_ic" type="number" min="0" max="1" step=".01"/></div>
        <div class="field"><label>最低 |IC IR|</label><input v-model.number="form.min_ic_ir" type="number" min="0" max="10" step=".1"/></div>
        <div class="field"><label>假发现率</label><input v-model.number="form.false_discovery_rate" type="number" min=".01" max=".25" step=".01"/></div>
        <div class="field"><label>最少IC观测</label><input v-model.number="form.min_ic_observations" type="number" min="10" max="1000"/></div>
        <button class="primary research-submit" :disabled="busy||!form.snapshot_id" @click="createResearch">
          <Activity v-if="busy" :size="15"/><FlaskConical v-else :size="15"/>
          {{busy?'正在检验因子…':'运行因子研究'}}
        </button>
      </div>
    </article>

    <article class="panel">
      <div class="panel-head research-result-head">
        <div><h3>研究结果</h3><p>选择一次历史研究，查看当时参数和不可变结论。</p></div>
        <select v-model="selectedRunId">
          <option v-for="run in runs" :key="run.id" :value="run.id">{{run.name}} · {{run.status}}</option>
        </select>
      </div>
      <div v-if="selectedRun?.status==='succeeded'&&selectedRun.metrics">
        <div class="research-kpis">
          <div><small>样本行数</small><b>{{selectedRun.metrics.sample_rows}}</b></div>
          <div><small>预测周期</small><b>{{selectedRun.metrics.forward_period}}日</b></div>
          <div><small>检验因子</small><b>{{factorRows.length}}</b></div>
          <div class="passed"><small>通过筛选</small><b>{{selectedRun.selected_feature_slugs.length}}</b></div>
          <div><small>训练区检验区间</small><b>{{selectedRun.metrics.date_min}} → {{selectedRun.metrics.date_max}}</b></div>
          <div><small>未读取区域</small><b>{{selectedRun.metrics.research_protocol?.training_boundary}} → {{selectedRun.metrics.full_date_max}}</b></div>
        </div>

        <div class="factor-result-table">
          <div class="factor-result-row head">
            <span>因子</span><span>筛选</span><span>覆盖率</span><span>Rank IC</span>
            <span>IC IR</span><span>p 值</span><span>BH q 值</span><span>年化分层差</span><span>换手率</span><span>结论</span>
          </div>
          <div v-for="row in factorRows" :key="row.slug" class="factor-result-row">
            <b>{{row.slug}}</b>
            <span><i class="screen-status" :class="{passed:row.passed}"><CheckCircle2 v-if="row.passed" :size="12"/><XCircle v-else :size="12"/>{{row.passed?'通过':'淘汰'}}</i></span>
            <span>{{percent(row.coverage)}}</span>
            <span :class="{positive:Number(row.rank_ic_mean)>0,negative:Number(row.rank_ic_mean)<0}">{{number(row.rank_ic_mean)}}</span>
            <span>{{number(row.rank_ic_ir,2)}}</span>
            <span>{{number(row.rank_ic_p_value,4)}}</span>
            <span>{{number(row.rank_ic_q_value,4)}}</span>
            <span>{{percent(row.quantile?.annualized_spread)}}</span>
            <span>{{percent(row.quantile?.turnover)}}</span>
            <small>{{row.reasons?.join('、')||'达到全部门槛'}}</small>
          </div>
        </div>

        <div v-if="factorSlugs.length" class="correlation-section">
          <div><h3>因子Rank相关性</h3><p>绝对相关性越接近1，两个因子提供的信息越重复。</p></div>
          <div class="correlation-scroll">
            <div class="correlation-grid" :style="{gridTemplateColumns:`140px repeat(${factorSlugs.length},72px)`}">
              <b></b><b v-for="slug in factorSlugs" :key="`head-${slug}`" :title="slug">{{slug}}</b>
              <template v-for="left in factorSlugs" :key="left">
                <b :title="left">{{left}}</b>
                <span v-for="right in factorSlugs" :key="`${left}-${right}`" :style="correlationColor(correlation(left,right))">
                  {{number(correlation(left,right),2)}}
                </span>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="selectedRun" class="empty research-empty">
        <RefreshCw :size="22"/><b>{{selectedRun.status}}</b><span>{{selectedRun.error_message||'任务尚未生成可用结果'}}</span>
      </div>
      <div v-else class="empty research-empty">尚无因子研究记录，请先选择快照并运行检验。</div>
    </article>
  </section>
</template>

<style scoped>
.factor-hero{display:flex;align-items:center;justify-content:space-between}.factor-hero>svg{color:#45d7c5;opacity:.75}
.research-notice{display:flex;align-items:center;gap:7px;margin:14px 0;padding:10px 13px;border:1px solid #bce8d9;border-radius:8px;background:#eaf8f3;color:#157b59;font-size:11px}
.research-create{margin:18px 0}.panel-head>svg{color:#3978c8}
.research-form{display:grid;grid-template-columns:1fr 1.5fr repeat(8,.65fr) auto;gap:10px;align-items:end}.research-form .field{min-width:0;margin:0}.research-form .field>label{white-space:nowrap}
.research-submit{align-self:end;justify-content:center;white-space:nowrap}
.research-result-head select{min-width:260px}
.research-kpis{display:grid;grid-template-columns:repeat(4,.7fr) repeat(2,1.3fr);gap:9px;margin-bottom:16px}
.research-kpis>div{padding:12px;border:1px solid #e3e9f0;border-radius:9px;background:#fafbfd}.research-kpis small,.research-kpis b{display:block}.research-kpis small{color:#8a96a7;font-size:9px}.research-kpis b{margin-top:5px;color:#344358;font-size:13px}.research-kpis .passed{border-color:#bde8d9;background:#effaf6}.research-kpis .passed b{color:#16805d}
.factor-result-table{overflow:hidden;border:1px solid #e2e8ef;border-radius:10px}.factor-result-row{display:grid;grid-template-columns:1.2fr .7fr .7fr .7fr .65fr .65fr .65fr .9fr .7fr 1.3fr;align-items:center;min-width:1120px;padding:10px 12px;border-top:1px solid #edf0f4;color:#526075;font-size:10px}.factor-result-row:first-child{border-top:0}.factor-result-row.head{background:#f6f8fb;color:#8793a3;font-size:9px;font-weight:700}.factor-result-row>b{color:#334359}.factor-result-row small{color:#8793a3}.positive{color:#16805d!important}.negative{color:#c65050!important}
.screen-status{display:inline-flex;align-items:center;gap:4px;padding:4px 6px;border-radius:12px;background:#f8e9e9;color:#b74646;font-style:normal;font-size:8px}.screen-status.passed{background:#e4f6ef;color:#14785a}
.correlation-section{margin-top:22px}.correlation-section h3{margin:0;font-size:14px}.correlation-section p{margin:4px 0 11px;color:#8a96a7;font-size:9px}.correlation-scroll{overflow:auto;border:1px solid #e1e7ee;border-radius:9px}.correlation-grid{display:grid;min-width:max-content}.correlation-grid>*{height:38px;display:grid;place-items:center;padding:0 7px;border-right:1px solid #edf0f4;border-bottom:1px solid #edf0f4;font-size:8px}.correlation-grid>b{overflow:hidden;background:#f7f9fb;color:#69778a;text-overflow:ellipsis;white-space:nowrap}.correlation-grid>span{font-variant-numeric:tabular-nums}
.research-empty{min-height:180px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px}.research-empty span{color:#8b97a7;font-size:10px}
@media(max-width:1200px){.research-form{grid-template-columns:repeat(4,1fr)}.snapshot-field{grid-column:span 2}.research-submit{grid-column:span 2}.research-kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){.research-form{grid-template-columns:1fr 1fr}.snapshot-field,.research-submit{grid-column:1/-1}.research-result-head{align-items:flex-start;flex-direction:column}.research-result-head select{width:100%;min-width:0}.research-kpis{grid-template-columns:1fr 1fr}.research-kpis>div:last-child{grid-column:1/-1}}
</style>
