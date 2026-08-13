<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {AlertTriangle,ArrowLeft,CheckCircle2,Download,GitBranch,Sparkles} from 'lucide-vue-next'
import {api} from '../api'
import {downloadApiFile} from '../download'

const route=useRoute()
const router=useRouter()
const item=ref<any>(null)
const loading=ref(true)
const loadError=ref('')
const features=computed(()=>Object.entries(item.value?.profile?.features||{}))
const warnings=computed(()=>item.value?.profile?.warnings||[])
const downloading=ref(false)
const downloadError=ref('')

async function downloadSnapshot(){
  if(!item.value||downloading.value)return
  downloading.value=true;downloadError.value=''
  try{await downloadApiFile(`/data-center/materializations/${item.value.id}/artifact`,`feature-snapshot-${String(item.value.id).slice(0,8)}.parquet`)}
  catch(exception:any){downloadError.value=exception.message||'下载失败，请稍后重试'}
  finally{downloading.value=false}
}

const failure=computed(()=>{
  const raw=String(item.value?.error_message||'').trim()
  if(!raw)return null
  if(raw.includes('Infinity')||raw.includes('invalid input syntax for type json')){
    return {
      title:'因子结果中出现了无穷值，快照未能保存',
      reason:'部分股票在停牌日成交量为 0，量价确认因子计算出了 Infinity；数据库无法把该值写入快照画像。',
      action:'系统已在新版本中把这类无效值安全转为空值。请返回数据中心，使用同一数据版本重新生成快照。',
    }
  }
  if(raw.includes('missing factor columns')){
    return {title:'快照缺少所选因子列',reason:'因子定义与实际计算产物不一致。',action:'请重新选择有效因子并生成新快照。'}
  }
  return {title:'快照生成失败',reason:raw.split('\n')[0],action:'请根据下方技术详情检查输入数据和因子定义，然后重新生成快照。'}
})

function metric(value:any){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—'
  return Number(value).toFixed(6).replace(/\.?0+$/,'')
}

onMounted(async()=>{
  try{item.value=(await api.get(`/data-center/materializations/${route.params.id}`)).data}
  catch(exception:any){loadError.value=exception.response?.data?.detail||exception.message}
  finally{loading.value=false}
})
</script>

<template>
  <section class="workflow">
    <div class="crumb"><button @click="router.push('/data-center')"><ArrowLeft :size="15"/>返回数据中心</button><span>特征快照详情</span></div>
    <div v-if="loading" class="panel empty">正在读取特征快照…</div>
    <div v-else-if="loadError" class="panel error-box">{{loadError}}</div>
    <template v-else-if="item">
      <article class="model-hero">
        <div class="feature-icon purple-bg"><Sparkles :size="24"/></div>
        <div><span class="eyebrow dark">FEATURE SNAPSHOT</span><h2>{{item.name}}</h2><p>{{item.row_count??'—'}} 行 · {{features.length}} 个特征</p></div>
        <div class="snapshot-actions"><button class="primary" :disabled="item.status!=='ready'||!item.artifact_uri||downloading" @click="downloadSnapshot"><Download :size="15"/>{{downloading?'正在下载…':'下载 Parquet'}}</button><i class="status" :class="item.status">{{item.status}}</i></div>
      </article>
      <p v-if="downloadError" class="error-box snapshot-download-error">{{downloadError}}</p>

      <article v-if="failure" class="failure-card">
        <div class="failure-icon"><AlertTriangle :size="23"/></div>
        <div class="failure-copy">
          <span>失败原因</span><h3>{{failure.title}}</h3><p>{{failure.reason}}</p>
          <div class="failure-action"><b>如何处理</b>{{failure.action}}</div>
          <details><summary>查看技术详情</summary><pre>{{item.error_message}}</pre></details>
        </div>
      </article>

      <article v-if="warnings.length" class="warning-card">
        <CheckCircle2 :size="18"/>
        <div><b>快照已安全处理异常数值</b><p v-for="warning in warnings" :key="`${warning.feature}-${warning.code}`">{{warning.feature}}：{{warning.count}} 个非有限值已转为空值，不会污染统计画像和后续因子检验。</p></div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h3>特征分布画像</h3><p>{{item.profile?.date_min||'—'}} → {{item.profile?.date_max||'—'}}</p></div></div>
        <div v-if="features.length" class="data-table">
          <div class="data-row header"><span>特征</span><span>缺失率</span><span>均值 / 标准差</span><span>范围</span></div>
          <div v-for="[name,raw] in features" :key="name" class="data-row">
            <code>{{name}}</code><span>{{metric((raw as any).missing_rate*100)}}%</span>
            <span>{{metric((raw as any).mean)}} / {{metric((raw as any).std)}}</span>
            <span>{{metric((raw as any).min)}} → {{metric((raw as any).max)}}</span>
          </div>
        </div>
        <div v-else class="empty snapshot-empty">{{item.status==='failed'?'任务在写入画像前失败，因此没有可展示的特征统计。':'暂无特征统计。'}}</div>
      </article>

      <div class="detail-grid">
        <article class="panel"><div class="panel-head"><div><h3>不可变标识</h3><p>用于数据集和漂移检查</p></div></div><dl class="detail-list"><div><dt>内容 SHA256</dt><dd><code>{{item.content_sha256||'—'}}</code></dd></div><div><dt>数据版本</dt><dd><RouterLink :to="`/data-center/versions/${item.data_version_id}`">{{item.data_version_id}}</RouterLink></dd></div><div><dt>产物地址</dt><dd><code>{{item.artifact_uri||'—'}}</code></dd></div></dl></article>
        <article class="panel"><div class="panel-head"><div><h3>完整血缘</h3><p>数据版本、特征定义和物化管线</p></div><GitBranch :size="18"/></div><div class="artifact"><code>{{JSON.stringify(item.lineage,null,2)}}</code></div></article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.failure-card{display:grid;grid-template-columns:44px 1fr;gap:13px;margin:16px 0;padding:17px;border:1px solid #f2c4bd;border-radius:13px;background:linear-gradient(135deg,#fff8f6,#fff);box-shadow:0 8px 24px rgba(166,58,43,.07)}
.failure-icon{width:42px;height:42px;display:grid;place-items:center;border-radius:11px;background:#fde8e4;color:#c64f3d}.failure-copy>span{color:#b85a4b;font-size:9px;font-weight:800;letter-spacing:.12em}.failure-copy h3{margin:4px 0 6px;color:#71382f;font-size:15px}.failure-copy p{margin:0;color:#795d58;font-size:10px;line-height:1.65}.failure-action{margin-top:11px;padding:10px 12px;border-radius:8px;background:#fff0ed;color:#825047;font-size:10px}.failure-action b{margin-right:8px;color:#b94c3c}.failure-copy details{margin-top:10px;color:#8b6b66;font-size:9px}.failure-copy summary{cursor:pointer}.failure-copy pre{max-height:180px;margin:8px 0 0;padding:10px;overflow:auto;border-radius:7px;background:#342521;color:#f5d7d1;font:8px/1.55 Consolas,monospace;white-space:pre-wrap}
.warning-card{display:flex;align-items:flex-start;gap:10px;margin:16px 0;padding:13px 15px;border:1px solid #bde4d5;border-radius:11px;background:#effaf6;color:#167858}.warning-card>svg{flex:none}.warning-card b{font-size:11px}.warning-card p{margin:4px 0 0;color:#587c70;font-size:9px}.snapshot-empty{min-height:130px}
.snapshot-actions{display:flex;align-items:center;gap:10px;margin-left:auto}.model-hero>.status{margin-left:0}.snapshot-download-error{margin:0 0 16px}
@media(max-width:720px){.failure-card{grid-template-columns:1fr}.failure-icon{width:36px;height:36px}}
</style>
