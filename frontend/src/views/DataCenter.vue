<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {api} from '../api'
import {user} from '../auth'
import {selectedProjectId} from '../projects'
import {Check,CheckCircle2,Database,Download,Layers3,Plus,Search,Sparkles} from 'lucide-vue-next'

const sources=ref<any[]>([])
const versions=ref<any[]>([])
const features=ref<any[]>([])
const snapshots=ref<any[]>([])
const factorLibrary=ref<any[]>([])
const error=ref('')
const notice=ref('')
const busy=ref(false)
const factorSearch=ref('')
const isAdmin=computed(()=>user.value?.role==='admin')

const sourceForm=ref({
  name:'演示日线数据源',
  slug:'demo-daily',
  provider:'demo',
  asset_type:'equity_daily',
  configuration:{},
})
type SyncDraft={
  source_id:string
  symbols:string
  start_date:string
  end_date:string
  universe_policy:{enabled:boolean;min_history_days:number;min_price:number;liquidity_lookback:number;min_avg_turnover:number;max_members:number}
}

const defaultSyncForm:SyncDraft={
  source_id:'',
  symbols:'DEMO1,DEMO2,DEMO3,DEMO4,DEMO5',
  start_date:'2018-01-01',
  end_date:'2024-12-31',
  universe_policy:{enabled:true,min_history_days:120,min_price:3,liquidity_lookback:20,min_avg_turnover:1000000,max_members:100},
}
const syncDraftKey=`quant_data_sync_draft:${selectedProjectId.value||'default'}`
const hadSavedSyncDraft=sessionStorage.getItem(syncDraftKey)!==null
function restoreSyncDraft():SyncDraft{
  try{
    const saved=JSON.parse(sessionStorage.getItem(syncDraftKey)||'{}') as Partial<SyncDraft>
    return {...defaultSyncForm,...saved}
  }catch{
    return {...defaultSyncForm}
  }
}
const syncForm=ref(restoreSyncDraft())
const featureForm=ref({
  name:'20日收益率',
  slug:'return_20d',
  family:'technical',
  implementation:'return',
  window:20,
  short_window:5,
  long_window:20,
  expression:'close / mean(close, 20) - 1',
  description:'过去20个交易日收益率',
})
const materialForm=ref({
  name:'基础量价特征快照',
  data_version_id:'',
  feature_definition_ids:[] as string[],
})

const readyVersions=computed(()=>
  versions.value.filter(item=>item.layer==='standardized'&&item.status==='ready')
)
const selectedSource=computed(()=>
  sources.value.find(item=>item.id===syncForm.value.source_id)
)
const selectedVersion=computed(()=>
  readyVersions.value.find(item=>item.id===materialForm.value.data_version_id)
)
const currentFactors=computed(()=>{
  const latest=new Map<string,any>()
  for(const feature of features.value){
    const existing=latest.get(feature.slug)
    if(!existing||Number(feature.version)>Number(existing.version))latest.set(feature.slug,feature)
  }
  return [...latest.values()]
})
const filteredFactors=computed(()=>{
  const keyword=factorSearch.value.trim().toLowerCase()
  if(!keyword)return currentFactors.value
  return currentFactors.value.filter(factor=>
    [factor.name,factor.slug,factor.family,factor.implementation]
      .some(value=>String(value||'').toLowerCase().includes(keyword))
  )
})
const selectedFactorIds=computed(()=>new Set(materialForm.value.feature_definition_ids))
const allVisibleFactorsSelected=computed(()=>
  filteredFactors.value.length>0
  &&filteredFactors.value.every(factor=>selectedFactorIds.value.has(factor.id))
)
const pipelineSteps=computed(()=>[
  {number:1,label:'数据来源',done:Boolean(selectedSource.value),detail:selectedSource.value?.name||'请选择数据源'},
  {number:2,label:'标准数据',done:Boolean(readyVersions.value.length),detail:readyVersions.value.length?`${readyVersions.value.length} 个可用版本`:'等待同步'},
  {number:3,label:'模型因子',done:Boolean(currentFactors.value.length),detail:currentFactors.value.length?`${currentFactors.value.length} 个因子`:'等待定义'},
  {number:4,label:'因子快照',done:Boolean(snapshots.value.some(item=>item.status==='ready')),detail:snapshots.value.some(item=>item.status==='ready')?'已可用于建模':'等待生成'},
])
const expressionExamples=[
  {name:'均线偏离',expression:'close / mean(close, 20) - 1'},
  {name:'量价动量',expression:'pct_change(close, 10) * volume / mean(volume, 20)'},
  {name:'价格区间',expression:'(close - min(low, 20)) / (max(high, 20) - min(low, 20))'},
  {name:'短长均线差',expression:'mean(close, 5) / mean(close, 20) - 1'},
]

watch(syncForm,value=>{
  // Keep the user's market universe and date range while navigating to a
  // version detail page and back.  The draft is isolated by project and only
  // lasts for the current browser session.
  sessionStorage.setItem(syncDraftKey,JSON.stringify(value))
},{deep:true})

function versionSource(version:any){
  return sources.value.find(source=>source.id===version.source_id)
}

function versionLabel(version:any){
  const specification=version.specification||{}
  const source=versionSource(version)
  const symbols=Array.isArray(specification.symbols)?specification.symbols:[]
  const provider=String(source?.provider||'unknown').toUpperCase()
  const dates=`${specification.start_date||'未知'} 至 ${specification.end_date||'未知'}`
  const identity=String(version.id).slice(0,8)
  const universe=specification.universe_policy?.enabled?'动态股票池':'静态候选集'
  return `${source?.name||provider} · ${dates} · ${symbols.length}只候选 · ${universe} · ${version.row_count||0}行 · ${String(version.content_sha256||'').slice(0,12)} · ${identity}`
}

async function load(){
  const [sourceResponse,versionResponse,featureResponse,snapshotResponse,libraryResponse]=await Promise.all([
    api.get('/data-center/sources'),
    api.get('/data-center/versions'),
    api.get('/data-center/features'),
    api.get('/data-center/materializations'),
    api.get('/data-center/factor-library'),
  ])
  sources.value=sourceResponse.data
  versions.value=versionResponse.data
  features.value=featureResponse.data
  snapshots.value=snapshotResponse.data
  factorLibrary.value=libraryResponse.data
  // On the first visit in a browser session, continue from the latest usable
  // version instead of presenting demo symbols unrelated to the user's data.
  if(!hadSavedSyncDraft&&readyVersions.value.length){
    const latest=readyVersions.value[0]
    const specification=latest.specification||{}
    syncForm.value={
      source_id:latest.source_id,
      symbols:Array.isArray(specification.symbols)?specification.symbols.join(','):defaultSyncForm.symbols,
      start_date:specification.start_date||defaultSyncForm.start_date,
      end_date:specification.end_date||defaultSyncForm.end_date,
      universe_policy:{...defaultSyncForm.universe_policy,...(specification.universe_policy||{})},
    }
  }
  if(!sources.value.some(item=>item.id===syncForm.value.source_id)&&sources.value.length){
    syncForm.value.source_id=(
      sources.value.find(item=>item.provider==='baostock')||sources.value[0]
    ).id
  }
  if(!materialForm.value.data_version_id&&readyVersions.value.length){
    materialForm.value.data_version_id=readyVersions.value[0].id
  }
  const validFactorIds=new Set(currentFactors.value.map(item=>item.id))
  materialForm.value.feature_definition_ids=materialForm.value.feature_definition_ids.filter(
    id=>validFactorIds.has(id)
  )
  if(!materialForm.value.feature_definition_ids.length&&currentFactors.value.length){
    materialForm.value.feature_definition_ids=currentFactors.value.map(item=>item.id)
  }
}

onMounted(()=>load().catch(exception=>error.value=exception.response?.data?.detail||exception.message))

async function wait(jobId:string){
  for(let index=0;index<300;index++){
    const job=(await api.get(`/jobs/${jobId}`)).data
    if(['succeeded','failed','canceled'].includes(job.status)){
      if(job.status!=='succeeded')throw new Error(job.error_message||'任务失败')
      return
    }
    await new Promise(resolve=>setTimeout(resolve,1000))
  }
  throw new Error('任务超时')
}

async function createSource(){
  busy.value=true
  error.value=''
  notice.value=''
  try{
    const response=await api.post('/data-center/sources',sourceForm.value)
    await load()
    // A source registration and a synchronization selection are distinct.
    // Select the newly created source explicitly so the next synchronization
    // cannot silently keep using the previous provider.
    syncForm.value.source_id=response.data.id
    notice.value=`数据源“${response.data.name}”已登记并自动选中。`
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{
    busy.value=false
  }
}

async function sync(){
  busy.value=true
  error.value=''
  notice.value=''
  try{
    const response=await api.post('/data-center/sync',{
      ...syncForm.value,
      symbols:syncForm.value.symbols.split(',').map(symbol=>symbol.trim()).filter(Boolean),
    })
    await wait(response.data.job_id)
    await load()
    materialForm.value.data_version_id=response.data.resource_id
    notice.value='数据同步与质量检查完成，新的 Standardized 版本已自动带入因子快照。'
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{
    busy.value=false
  }
}

async function createFeature(){
  busy.value=true
  error.value=''
  notice.value=''
  try{
    const response=await api.post('/data-center/features',{
      name:featureForm.value.name,
      slug:featureForm.value.slug,
      family:featureForm.value.family,
      implementation:featureForm.value.implementation,
      description:featureForm.value.description,
      parameters:featureForm.value.implementation==='expression'
        ?{expression:featureForm.value.expression}
        :featureForm.value.implementation==='momentum_acceleration'
          ?{short_window:Number(featureForm.value.short_window),long_window:Number(featureForm.value.long_window)}
          :{window:Number(featureForm.value.window)},
    })
    await load()
    const sameSlugIds=new Set(
      features.value.filter(item=>item.slug===response.data.slug).map(item=>item.id)
    )
    materialForm.value.feature_definition_ids=[
      ...materialForm.value.feature_definition_ids.filter(id=>!sameSlugIds.has(id)),
      response.data.id,
    ]
    notice.value=`因子“${response.data.name} v${response.data.version}”已注册并自动加入快照。`
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{
    busy.value=false
  }
}

async function materialize(){
  busy.value=true
  error.value=''
  notice.value=''
  try{
    const response=await api.post('/data-center/materializations',materialForm.value)
    await wait(response.data.job_id)
    await load()
    notice.value='因子快照已生成，可以进入“研究数据集”开始构建训练样本。'
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{
    busy.value=false
  }
}

function applyFactorTemplate(template:any){
  const window=Number(template.default_window||20)
  featureForm.value={
    ...featureForm.value,
    name:`${window}日${template.name}`,
    slug:`${template.implementation}_${window}d`,
    family:template.family,
    implementation:template.implementation,
    window,
    description:template.description,
  }
}

function useExpressionExample(example:(typeof expressionExamples)[number]){
  featureForm.value={
    ...featureForm.value,
    name:`自定义${example.name}`,
    slug:`custom_${Date.now().toString().slice(-8)}`,
    family:'custom',
    implementation:'expression',
    expression:example.expression,
    description:`使用安全表达式生成的${example.name}因子`,
  }
}

function toggleFactor(factorId:string){
  const selected=new Set(materialForm.value.feature_definition_ids)
  if(selected.has(factorId))selected.delete(factorId)
  else selected.add(factorId)
  materialForm.value.feature_definition_ids=[...selected]
}

function selectAllVisibleFactors(){
  const selected=new Set(materialForm.value.feature_definition_ids)
  for(const factor of filteredFactors.value)selected.add(factor.id)
  materialForm.value.feature_definition_ids=[...selected]
}

function clearSelectedFactors(){
  materialForm.value.feature_definition_ids=[]
}
</script>

<template>
  <section>
    <div class="hero">
      <div>
        <span class="eyebrow">DATA TO MODEL FACTORS</span>
        <h2>从行情数据到可训练因子</h2>
        <p>沿一条流水线完成数据接入、质量检查、因子定义和不可变因子快照。</p>
      </div>
    </div>

    <p v-if="error" class="error-box">{{error}}</p>
    <p v-if="notice" class="pipeline-notice"><CheckCircle2 :size="17"/>{{notice}}</p>

    <div class="pipeline-progress">
      <div
        v-for="step in pipelineSteps"
        :key="step.number"
        class="pipeline-progress-item"
        :class="{done:step.done}"
      >
        <i><CheckCircle2 v-if="step.done" :size="15"/><template v-else>{{step.number}}</template></i>
        <div><b>{{step.label}}</b><small>{{step.detail}}</small></div>
      </div>
    </div>

    <article class="panel data-pipeline">
      <div class="pipeline-title">
        <div>
          <span class="eyebrow dark">RESEARCH DATA PIPELINE</span>
          <h2>数据与因子流水线</h2>
          <p>每一步的成功产物会自动成为下一步的默认输入。</p>
        </div>
        <span class="pipeline-definition">
          <Sparkles :size="16"/>
          因子 = 模型的一列输入特征
        </span>
      </div>

      <div class="pipeline-step">
        <div class="pipeline-marker"><i>1</i><span></span></div>
        <div class="pipeline-content">
          <div class="pipeline-step-head">
            <div><h3>选择数据来源</h3><p>日常研究只需选择已登记的数据源，不必重复创建。</p></div>
            <Database :size="20"/>
          </div>
          <div class="compact-grid source-selector">
            <div class="field">
              <label>当前数据源</label>
              <select v-model="syncForm.source_id">
                <option v-for="source in sources" :key="source.id" :value="source.id">
                  {{source.name}} · {{String(source.provider).toUpperCase()}}
                </option>
              </select>
            </div>
            <div v-if="selectedSource" class="selection-summary">
              <b>{{selectedSource.name}}</b>
              <span>{{String(selectedSource.provider).toUpperCase()}} · {{selectedSource.slug}}</span>
              <i class="status succeeded">ACTIVE</i>
            </div>
          </div>
          <details v-if="isAdmin" class="advanced-source">
            <summary><Plus :size="14"/>高级操作：登记新的数据提供方</summary>
            <div class="compact-grid advanced-source-form">
              <div class="field"><label>名称</label><input v-model="sourceForm.name"/></div>
              <div class="field"><label>标识</label><input v-model="sourceForm.slug"/></div>
              <div class="field">
                <label>提供方</label>
                <select v-model="sourceForm.provider">
                  <option value="demo">演示数据</option>
                  <option value="akshare">AKShare</option>
                  <option value="baostock">Baostock</option>
                </select>
              </div>
              <button class="secondary compact-action" :disabled="busy" @click="createSource">
                <Plus :size="15"/>登记并选中
              </button>
            </div>
          </details>
        </div>
      </div>

      <div class="pipeline-step">
        <div class="pipeline-marker"><i>2</i><span></span></div>
        <div class="pipeline-content">
          <div class="pipeline-step-head">
            <div><h3>同步并标准化行情</h3><p>一次任务同时生成 Raw 原始层、Standardized 标准层和质量报告。</p></div>
            <Download :size="20"/>
          </div>
          <div class="field"><label>股票代码（英文逗号分隔）</label><input v-model="syncForm.symbols"/></div>
          <details class="universe-policy" open>
            <summary>按日期动态股票池（只使用当时可见数据）</summary>
            <label class="universe-toggle"><input v-model="syncForm.universe_policy.enabled" type="checkbox"/>启用可交易性与流动性门禁</label>
            <div class="compact-grid universe-grid">
              <div class="field"><label>最少历史交易日</label><input v-model.number="syncForm.universe_policy.min_history_days" type="number" min="20" max="1000"/></div>
              <div class="field"><label>最低价格</label><input v-model.number="syncForm.universe_policy.min_price" type="number" min="0" step=".1"/></div>
              <div class="field"><label>流动性回看日</label><input v-model.number="syncForm.universe_policy.liquidity_lookback" type="number" min="5" max="252"/></div>
              <div class="field"><label>最低日均成交额代理</label><input v-model.number="syncForm.universe_policy.min_avg_turnover" type="number" min="0" step="100000"/></div>
              <div class="field"><label>每日最多成分股</label><input v-model.number="syncForm.universe_policy.max_members" type="number" min="3" max="1000"/></div>
            </div>
            <small>候选代码会全部保存，但每个交易日仅将当日满足历史长度、价格、成交量和流动性排名的股票送入因子研究与训练。</small>
          </details>
          <div class="compact-grid">
            <div class="field"><label>开始日期</label><input v-model="syncForm.start_date" type="date"/></div>
            <div class="field"><label>结束日期</label><input v-model="syncForm.end_date" type="date"/></div>
            <button class="primary compact-action" :disabled="busy||!sources.length" @click="sync">
              <Download :size="15"/>同步并通过质量门禁
            </button>
          </div>
          <div v-if="selectedVersion" class="step-output">
            <CheckCircle2 :size="16"/>
            <div><b>当前可用标准版本</b><span>{{versionLabel(selectedVersion)}}</span></div>
          </div>
        </div>
      </div>

      <div class="pipeline-step">
        <div class="pipeline-marker"><i>3</i><span></span></div>
        <div class="pipeline-content">
          <div class="pipeline-step-head">
            <div>
              <h3>定义模型因子</h3>
              <p>因子是从行情计算出的模型输入列；定义负责公式和参数，快照负责实际计算。</p>
            </div>
            <Sparkles :size="20"/>
          </div>
          <div class="factor-explainer">
            <b>例如</b>
            <span>20日收益率是一个动量因子</span>
            <span>20日波动率是一个风险因子</span>
            <span>量比是一个流动性/活跃度因子</span>
          </div>
          <template v-if="isAdmin">
            <div class="factor-mode-title">
              <div><b>内置因子库</b><span>{{factorLibrary.length}}种经过后端实现的计算方式</span></div>
              <button type="button" :class="{selected:featureForm.implementation==='expression'}" @click="useExpressionExample(expressionExamples[0])">
                <Sparkles :size="13"/>自由公式
              </button>
            </div>
            <div class="factor-templates">
              <button
                v-for="template in factorLibrary"
                :key="template.implementation"
                type="button"
                :class="{selected:featureForm.implementation===template.implementation}"
                @click="applyFactorTemplate(template)"
              >
                <b>{{template.name}}</b>
                <small>{{template.family}}</small>
              </button>
            </div>
            <div class="compact-grid factor-form">
              <div class="field"><label>因子名称</label><input v-model="featureForm.name"/></div>
              <div class="field"><label>因子标识</label><input v-model="featureForm.slug"/></div>
              <div class="field">
                <label>计算实现</label>
                <select v-model="featureForm.implementation">
                  <option v-for="template in factorLibrary" :key="template.implementation" :value="template.implementation">
                    {{template.name}}
                  </option>
                  <option value="expression">安全自由表达式</option>
                </select>
              </div>
              <template v-if="featureForm.implementation==='momentum_acceleration'">
                <div class="field"><label>短周期</label><input v-model.number="featureForm.short_window" type="number" min="1" max="499"/></div>
                <div class="field"><label>长周期</label><input v-model.number="featureForm.long_window" type="number" min="2" max="500"/></div>
              </template>
              <div v-else-if="featureForm.implementation!=='expression'" class="field">
                <label>回看窗口</label><input v-model.number="featureForm.window" type="number" min="1" max="500"/>
              </div>
              <button class="primary compact-action" :disabled="busy" @click="createFeature">
                <Plus :size="15"/>注册并加入快照
              </button>
            </div>
            <div v-if="featureForm.implementation==='expression'" class="expression-builder">
              <div class="expression-builder-head">
                <div><b>安全因子表达式</b><span>不执行Python代码，只允许行情字段和白名单滚动算子</span></div>
                <div class="expression-examples">
                  <button v-for="example in expressionExamples" :key="example.name" type="button" @click="useExpressionExample(example)">
                    {{example.name}}
                  </button>
                </div>
              </div>
              <textarea v-model="featureForm.expression" rows="3" spellcheck="false"/>
              <div class="expression-help">
                <span><b>字段</b> open high low close volume</span>
                <span><b>时序</b> lag delta pct_change mean std min max sum ema</span>
                <span><b>数学</b> abs log sqrt clip</span>
              </div>
            </div>
          </template>
          <div v-if="currentFactors.length" class="factor-inventory">
            <b>当前可用因子</b>
            <span v-for="factor in currentFactors" :key="factor.id">
              {{factor.slug}} <small>v{{factor.version}}</small>
            </span>
          </div>
        </div>
      </div>

      <div class="pipeline-step final-step">
        <div class="pipeline-marker"><i>4</i></div>
        <div class="pipeline-content">
          <div class="pipeline-step-head">
            <div><h3>生成不可变因子快照</h3><p>将标准行情与选定因子版本绑定，产物可直接用于创建研究数据集。</p></div>
            <Layers3 :size="20"/>
          </div>
          <div class="field"><label>快照名称</label><input v-model="materialForm.name"/></div>
          <div class="compact-grid snapshot-grid">
            <div class="snapshot-config-card version-config">
              <div class="snapshot-config-head">
                <div><b>标准数据版本</b><small>选择通过质量门禁的行情版本</small></div>
                <Database :size="17"/>
              </div>
              <select v-model="materialForm.data_version_id" class="version-select">
                <option disabled value="">请选择已就绪的标准数据版本</option>
                <option v-for="version in readyVersions" :key="version.id" :value="version.id">
                  {{versionLabel(version)}}
                </option>
              </select>
              <div v-if="selectedVersion" class="version-lock">
                <CheckCircle2 :size="18"/>
                <div>
                  <b>输入数据已锁定</b>
                  <span>{{versionSource(selectedVersion)?.name||'标准行情'}} · STANDARDIZED</span>
                  <code>{{String(selectedVersion.content_sha256||'').slice(0,20)}}…</code>
                </div>
              </div>
              <p class="snapshot-card-tip">快照会记录数据内容哈希，后续训练可以准确复现本次输入。</p>
            </div>
            <div class="snapshot-config-card factor-config">
              <div class="snapshot-config-head">
                <div><b>模型因子</b><small>自动使用每个因子的最新版本，可多选</small></div>
                <Sparkles :size="17"/>
              </div>
              <div class="factor-picker">
                <div class="factor-picker-toolbar">
                  <label class="factor-search">
                    <Search :size="14"/>
                    <input v-model="factorSearch" placeholder="搜索因子名称或标识"/>
                  </label>
                  <span class="factor-count">
                    已选 <b>{{materialForm.feature_definition_ids.length}}</b> / {{currentFactors.length}}
                  </span>
                  <button
                    type="button"
                    class="factor-picker-action"
                    :disabled="!filteredFactors.length||allVisibleFactorsSelected"
                    @click="selectAllVisibleFactors"
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    class="factor-picker-action muted"
                    :disabled="!materialForm.feature_definition_ids.length"
                    @click="clearSelectedFactors"
                  >
                    清空
                  </button>
                </div>
                <div v-if="filteredFactors.length" class="factor-options">
                  <button
                    v-for="feature in filteredFactors"
                    :key="feature.id"
                    type="button"
                    class="factor-option"
                    :class="{selected:selectedFactorIds.has(feature.id)}"
                    :aria-pressed="selectedFactorIds.has(feature.id)"
                    @click="toggleFactor(feature.id)"
                  >
                    <i class="factor-check">
                      <Check v-if="selectedFactorIds.has(feature.id)" :size="13"/>
                    </i>
                    <span class="factor-option-copy">
                      <b>{{feature.name}}</b>
                      <small>{{feature.slug}} · v{{feature.version}}</small>
                    </span>
                    <span class="factor-meta">
                      {{feature.implementation||feature.family||'factor'}}
                      <small v-if="feature.parameters?.window">{{feature.parameters.window}}日</small>
                    </span>
                  </button>
                </div>
                <div v-else class="factor-empty">
                  {{currentFactors.length?'没有匹配的模型因子':'尚未注册模型因子，请先完成第 3 步'}}
                </div>
              </div>
            </div>
          </div>
          <div v-if="selectedVersion" class="snapshot-summary">
            <div><small>数据范围</small><b>{{selectedVersion.specification?.start_date}} → {{selectedVersion.specification?.end_date}}</b></div>
            <div><small>股票数量</small><b>{{selectedVersion.specification?.symbols?.length||0}} 只</b></div>
            <div><small>数据行数</small><b>{{selectedVersion.row_count||0}}</b></div>
            <div><small>选中因子</small><b>{{materialForm.feature_definition_ids.length}} 个</b></div>
          </div>
          <div class="snapshot-actions">
            <RouterLink class="secondary link-button" to="/factor-research">
              <Sparkles :size="15"/>查看因子研究
            </RouterLink>
            <button
              class="primary snapshot-action"
              :disabled="busy||!materialForm.data_version_id||!materialForm.feature_definition_ids.length"
              @click="materialize"
            >
              <Layers3 :size="16"/>生成快照并进入因子检验
            </button>
          </div>
        </div>
      </div>
    </article>

    <article class="panel">
      <div class="panel-head"><div><h3>数据版本与质量</h3><p>最近200个不可变数据资产</p></div></div>
      <div class="table">
        <div class="tr th"><span>层级</span><span>状态</span><span>行数</span><span>内容哈希</span></div>
        <RouterLink v-for="version in versions" :key="version.id" class="tr product-link-row" :to="`/data-center/versions/${version.id}`">
          <b>{{version.layer}}</b>
          <span><i class="status" :class="version.status">{{version.status}}</i></span>
          <span>{{version.row_count||'—'}}</span>
          <code>{{version.content_sha256?.slice(0,16)||'—'}}</code>
        </RouterLink>
      </div>
    </article>

    <article class="panel">
      <div class="panel-head"><div><h3>特征快照</h3><p>分布画像、缺失率和完整血缘</p></div></div>
      <div class="table">
        <div class="tr th"><span>名称</span><span>状态</span><span>行数</span><span>内容哈希</span></div>
        <RouterLink v-for="snapshot in snapshots" :key="snapshot.id" class="tr product-link-row" :to="`/data-center/snapshots/${snapshot.id}`">
          <b>{{snapshot.name}}</b>
          <span><i class="status" :class="snapshot.status">{{snapshot.status}}</i></span>
          <span>{{snapshot.row_count||'—'}}</span>
          <code>{{snapshot.content_sha256?.slice(0,16)||'—'}}</code>
        </RouterLink>
      </div>
    </article>
  </section>
</template>

<style scoped>
.pipeline-notice{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:11px 14px;border:1px solid #bce8d9;border-radius:9px;background:#eaf8f3;color:#157b59;font-size:12px}
.pipeline-progress{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin:18px 0;overflow:hidden;border:1px solid #dfe6ef;border-radius:11px;background:#fff}
.pipeline-progress-item{display:flex;align-items:center;gap:10px;min-width:0;padding:13px 15px;position:relative}
.pipeline-progress-item:not(:last-child):after{content:'';position:absolute;right:0;width:1px;height:30px;background:#e4e9f0}
.pipeline-progress-item>i{width:28px;height:28px;display:grid;place-items:center;flex:none;border-radius:50%;background:#edf1f6;color:#728096;font-style:normal;font-size:11px;font-weight:700}
.pipeline-progress-item.done>i{background:#dff7ee;color:#16835f}
.pipeline-progress-item b,.pipeline-progress-item small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pipeline-progress-item b{font-size:12px;color:#314055}.pipeline-progress-item small{margin-top:3px;color:#8a96a6;font-size:10px}
.data-pipeline{padding:0;overflow:hidden;margin-bottom:16px}
.pipeline-title{display:flex;justify-content:space-between;align-items:center;padding:22px 25px;border-bottom:1px solid #e7ecf2;background:linear-gradient(110deg,#f8fbff,#f5faf9)}
.pipeline-title h2{font:700 20px Manrope;margin:4px 0}.pipeline-title p{margin:0;color:#7f8c9e;font-size:12px}
.pipeline-definition{display:flex;align-items:center;gap:7px;padding:9px 12px;border:1px solid #cce8e2;border-radius:20px;background:#ebfaf6;color:#177b62;font-size:11px;font-weight:700}
.pipeline-step{display:grid;grid-template-columns:56px 1fr;padding:0 25px}
.pipeline-marker{display:flex;flex-direction:column;align-items:center}
.pipeline-marker i{width:31px;height:31px;display:grid;place-items:center;flex:none;margin-top:25px;border-radius:50%;background:#1768d7;color:#fff;font-style:normal;font-size:12px;font-weight:700;box-shadow:0 0 0 5px #1768d712}
.pipeline-marker span{width:1px;flex:1;background:#dce4ed;margin:8px 0 -17px}
.pipeline-content{min-width:0;padding:24px 0 25px;border-bottom:1px solid #e9edf2}
.final-step .pipeline-content{border-bottom:0}
.pipeline-step-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:17px}
.pipeline-step-head h3{font:700 16px Manrope;margin:0}.pipeline-step-head p{margin:4px 0 0;color:#8793a4;font-size:11px}.pipeline-step-head>svg{color:#3978c8}
.compact-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;align-items:end}.compact-grid .field{margin-bottom:0}
.source-selector{grid-template-columns:minmax(260px,1.4fr) minmax(220px,.8fr)}
.selection-summary{min-height:42px;display:flex;align-items:center;gap:10px;padding:8px 11px;border:1px solid #e0e7ef;border-radius:8px;background:#f8fafc}
.selection-summary b{font-size:12px}.selection-summary span{margin-left:auto;color:#8592a3;font-size:10px}.selection-summary .status{flex:none}
.advanced-source{margin-top:12px;border:1px dashed #dce3eb;border-radius:8px;background:#fafbfd}
.advanced-source summary{display:flex;align-items:center;gap:6px;padding:10px 12px;color:#617086;font-size:11px;cursor:pointer}
.advanced-source-form{grid-template-columns:1fr 1fr 1fr auto;padding:0 12px 12px}
.compact-action{align-self:end;justify-content:center;white-space:nowrap;margin-bottom:0}
.universe-policy{margin:12px 0;padding:11px 12px;border:1px solid #dce7f3;border-radius:9px;background:#f8fbff}.universe-policy summary{color:#36516f;font-size:11px;font-weight:700;cursor:pointer}.universe-policy>small{display:block;margin-top:9px;color:#718096;font-size:9px;line-height:1.55}.universe-toggle{display:flex;align-items:center;gap:7px;margin:11px 0;color:#41617f;font-size:10px}.universe-toggle input{width:auto}.universe-grid{grid-template-columns:repeat(5,minmax(0,1fr))}
.step-output{display:flex;align-items:flex-start;gap:9px;margin-top:13px;padding:10px 12px;border-radius:8px;background:#edf8f4;color:#167b5a}
.step-output b,.step-output span{display:block}.step-output b{font-size:11px}.step-output span{margin-top:3px;color:#628276;font-size:10px}
.factor-explainer{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;padding:10px 12px;border-radius:8px;background:#f4f7fb;color:#657387;font-size:10px}
.factor-explainer b{color:#334156}.factor-explainer span{padding:4px 7px;border-radius:5px;background:#fff;border:1px solid #e1e7ee}
.factor-mode-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:2px 0 9px}
.factor-mode-title>div b,.factor-mode-title>div span{display:block}.factor-mode-title>div b{color:#354358;font-size:11px}.factor-mode-title>div span{margin-top:2px;color:#8a96a6;font-size:9px}
.factor-mode-title>button{display:flex;align-items:center;gap:5px;padding:7px 10px;border:1px solid #d5e1ef;border-radius:7px;background:#fff;color:#52637a;font-size:9px}
.factor-mode-title>button.selected{border-color:#8cb7ed;background:#edf6ff;color:#1768d7}
.factor-templates{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:13px}
.factor-templates button{min-width:0;border:1px solid #dbe3ec;border-radius:8px;background:#fff;padding:8px;color:#627086;text-align:left}
.factor-templates button b,.factor-templates button small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.factor-templates button b{font-size:9px}.factor-templates button small{margin-top:3px;color:#97a2b1;font-size:8px;text-transform:uppercase}
.factor-templates button:hover,.factor-templates button.selected{border-color:#6aa2e7;background:#edf5ff;color:#1768d7}
.factor-form{grid-template-columns:1.1fr 1.1fr 1fr .65fr auto}
.expression-builder{margin:13px 0;padding:12px;border:1px solid #dce6f2;border-radius:9px;background:#f8fbff}
.expression-builder-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:9px}.expression-builder-head b,.expression-builder-head span{display:block}.expression-builder-head b{font-size:11px}.expression-builder-head span{margin-top:3px;color:#8290a2;font-size:9px}
.expression-examples{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}.expression-examples button{padding:4px 6px;border:1px solid #d7e2ef;border-radius:5px;background:#fff;color:#527094;font-size:8px}
.expression-builder textarea{width:100%;resize:vertical;border:1px solid #ccd9e8;border-radius:7px;background:#10233e;color:#bfe1ff;padding:10px;font:10px/1.6 Consolas,monospace}
.expression-help{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;color:#718096;font-size:8px}.expression-help b{color:#33455c}
.factor-inventory{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:13px;font-size:10px}
.factor-inventory>b{color:#566579}.factor-inventory>span{padding:5px 8px;border-radius:6px;background:#f0ebfd;color:#6b4eb7}.factor-inventory small{opacity:.75}
.snapshot-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:stretch;margin-top:12px}
.snapshot-config-card{min-width:0;padding:13px;border:1px solid #e0e7ef;border-radius:11px;background:#fafbfd}
.snapshot-config-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}
.snapshot-config-head b,.snapshot-config-head small{display:block}.snapshot-config-head b{color:#304057;font-size:11px}.snapshot-config-head small{margin-top:3px;color:#8a96a6;font-size:9px;font-weight:400}
.snapshot-config-head>svg{flex:none;color:#3978c8}
.version-config{display:flex;flex-direction:column}.version-select{width:100%;height:42px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;background:#fff;font-size:11px}
.version-lock{display:flex;align-items:flex-start;gap:9px;margin-top:10px;padding:12px;border:1px solid #cce9de;border-radius:8px;background:#eef9f5;color:#167b5a}
.version-lock>svg{flex:none;margin-top:1px}.version-lock b,.version-lock span,.version-lock code{display:block}.version-lock b{font-size:10px}.version-lock span{margin-top:3px;color:#67877c;font-size:9px}.version-lock code{margin-top:6px;color:#5d776f;font-size:8px}
.snapshot-card-tip{margin:auto 0 0;padding-top:12px;color:#8995a5;font-size:9px;line-height:1.5}
.factor-picker{overflow:hidden;border:1px solid #dce4ed;border-radius:10px;background:#fff;transition:border-color .18s,box-shadow .18s}
.factor-picker:focus-within{border-color:#82ace3;box-shadow:0 0 0 3px #1768d710}
.factor-picker-toolbar{display:flex;align-items:center;gap:7px;padding:8px;border-bottom:1px solid #e8edf2;background:#f8fafc}
.factor-search{display:flex;align-items:center;gap:6px;min-width:0;flex:1;margin:0;padding:0 9px;border:1px solid #dfe6ee;border-radius:7px;background:#fff;color:#8a96a6}
.factor-search input{min-width:0;height:31px;padding:0;border:0;background:transparent;box-shadow:none;font-size:10px}
.factor-search input:focus{outline:0}
.factor-count{white-space:nowrap;color:#7c8999;font-size:9px}.factor-count b{color:#1768d7;font-size:11px}
.factor-picker-action{padding:5px 7px;border:0;border-radius:5px;background:#e6f0fd;color:#1768d7;font-size:9px;font-weight:700;cursor:pointer}
.factor-picker-action.muted{background:#edf0f4;color:#69778a}.factor-picker-action:disabled{opacity:.4;cursor:not-allowed}
.factor-options{display:grid;gap:5px;max-height:184px;padding:7px;overflow:auto}
.factor-option{display:grid;grid-template-columns:22px minmax(0,1fr) auto;align-items:center;gap:8px;width:100%;padding:9px;border:1px solid transparent;border-radius:7px;background:transparent;color:#3d4b5f;text-align:left;cursor:pointer;transition:background .15s,border-color .15s}
.factor-option:hover{border-color:#d8e4f3;background:#f7faff}.factor-option.selected{border-color:#b9d5f7;background:#eef6ff}
.factor-check{width:19px;height:19px;display:grid;place-items:center;border:1px solid #cbd5e1;border-radius:5px;background:#fff;color:#fff;font-style:normal}
.factor-option.selected .factor-check{border-color:#1768d7;background:#1768d7}
.factor-option-copy{min-width:0}.factor-option-copy b,.factor-option-copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.factor-option-copy b{font-size:11px}.factor-option-copy small{margin-top:3px;color:#8a96a6;font-size:9px}
.factor-meta{display:flex;align-items:center;gap:5px;padding:4px 6px;border-radius:5px;background:#f0f3f7;color:#657387;font-size:8px;text-transform:uppercase}
.factor-meta small{color:#1768d7;font-size:8px;text-transform:none}.factor-empty{padding:28px 12px;color:#8c98a8;text-align:center;font-size:10px}
.snapshot-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:13px 0}
.snapshot-summary>div{padding:10px;border:1px solid #e4e9ef;border-radius:8px;background:#fafbfd}.snapshot-summary small,.snapshot-summary b{display:block}.snapshot-summary small{color:#8b97a7;font-size:9px}.snapshot-summary b{margin-top:4px;color:#344257;font-size:11px}
.snapshot-actions{display:flex;justify-content:flex-end;gap:8px}.snapshot-action{margin-left:0}.data-pipeline+article.panel,article.panel+article.panel{margin-top:16px}
@media(max-width:1000px){.universe-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.pipeline-progress{grid-template-columns:repeat(2,1fr)}.pipeline-progress-item:nth-child(2):after{display:none}.factor-templates{grid-template-columns:repeat(4,minmax(0,1fr))}.factor-form{grid-template-columns:1fr 1fr}.factor-form .compact-action{grid-column:1/-1}.advanced-source-form{grid-template-columns:1fr 1fr}.advanced-source-form .compact-action{grid-column:1/-1}}
@media(max-width:720px){.pipeline-progress{grid-template-columns:1fr}.pipeline-progress-item:after{display:none}.pipeline-title{align-items:flex-start;gap:14px;flex-direction:column}.pipeline-step{grid-template-columns:38px 1fr;padding:0 14px}.pipeline-marker i{width:28px;height:28px}.compact-grid,.source-selector,.factor-form,.snapshot-grid{grid-template-columns:1fr}.factor-templates{grid-template-columns:repeat(2,minmax(0,1fr))}.factor-mode-title,.expression-builder-head{align-items:flex-start;flex-direction:column}.expression-examples{justify-content:flex-start}.advanced-source-form .compact-action,.factor-form .compact-action{grid-column:auto}.selection-summary{flex-wrap:wrap}.selection-summary span{margin-left:0}.snapshot-summary{grid-template-columns:1fr 1fr}.snapshot-actions{align-items:stretch;flex-direction:column}.snapshot-action{width:100%;justify-content:center}}
</style>
