<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../api'
import {ArrowLeft,Database,Download,ShieldCheck} from 'lucide-vue-next'
const route=useRoute(),router=useRouter(),item=ref<any>(null),loading=ref(true),downloading=ref(false),downloadError=ref('')
const canDownload=computed(()=>item.value?.status==='ready'&&Boolean(item.value?.artifact_uri))
async function downloadDetail(){
  if(!item.value||downloading.value)return
  downloading.value=true;downloadError.value=''
  try{
    const response=await api.get(`/data-center/versions/${item.value.id}/download`,{responseType:'blob'})
    const url=URL.createObjectURL(new Blob([response.data],{type:'text/csv;charset=utf-8'}))
    const anchor=document.createElement('a')
    anchor.href=url;anchor.download=`data-version-${String(item.value.id).slice(0,8)}.csv`
    document.body.appendChild(anchor);anchor.click();anchor.remove()
    URL.revokeObjectURL(url)
  }catch(exception:any){downloadError.value=exception.response?.data?.detail||'下载失败，请稍后重试'}
  finally{downloading.value=false}
}
onMounted(async()=>{try{item.value=(await api.get(`/data-center/versions/${route.params.id}`)).data}finally{loading.value=false}})
</script>
<template><section class="workflow"><div class="crumb"><button @click="router.push('/data-center')"><ArrowLeft :size="15"/>返回数据中心</button><span>数据质量详情</span></div><div v-if="loading" class="panel empty">正在读取数据版本…</div><template v-else-if="item"><article class="model-hero"><div class="feature-icon"><Database :size="24"/></div><div><span class="eyebrow dark">{{item.layer}}</span><h2>{{item.specification?.name||'行情研究数据'}}</h2><p>{{item.specification?.start_date}} 至 {{item.specification?.end_date}}</p></div><i class="status" :class="item.status">{{item.status}}</i></article><article class="panel download-card"><div><span class="eyebrow dark">FULL ROW EXPORT</span><h3>下载全部数据明细</h3><p>CSV 可直接用 Excel、WPS、Numbers 或 Python 打开；包含此版本的每一条记录。字段顺序为日期、股票代码、开高低收、成交量，标准化版本会额外包含股票池资格和排名。</p><small>文件使用 UTF-8 编码，中文和股票代码可正常显示。</small><p v-if="downloadError" class="download-error">{{downloadError}}</p></div><button class="primary" :disabled="!canDownload||downloading" @click="downloadDetail"><Download :size="16"/>{{downloading?'正在准备文件…':'下载 CSV 明细'}}</button></article><div class="detail-grid"><article class="panel"><div class="panel-head"><div><h3>完整性与覆盖</h3><p>标准化质量门禁结果</p></div><ShieldCheck :size="18"/></div><dl class="detail-list"><div><dt>记录行数</dt><dd>{{item.row_count}}</dd></div><div><dt>标的数量</dt><dd>{{item.quality_report?.symbol_count??'—'}}</dd></div><div><dt>日期范围</dt><dd>{{item.quality_report?.date_min||'—'}} → {{item.quality_report?.date_max||'—'}}</dd></div><div><dt>日历缺失</dt><dd>{{item.quality_report?.missing_calendar_rows??0}}</dd></div><div><dt>停牌记录</dt><dd>{{item.quality_report?.suspended_rows??0}}</dd></div><div><dt>质量警告</dt><dd>{{item.quality_report?.warnings?.join('；')||'无'}}</dd></div></dl></article><article class="panel"><div class="panel-head"><div><h3>版本与血缘</h3><p>定位原始数据和转换规则</p></div></div><dl class="detail-list"><div><dt>内容 SHA256</dt><dd><code>{{item.content_sha256}}</code></dd></div><div><dt>父版本</dt><dd><code>{{item.parent_id||'—'}}</code></dd></div><div><dt>任务</dt><dd><code>{{item.job_id||'—'}}</code></dd></div><div><dt>产物地址</dt><dd><code>{{item.artifact_uri}}</code></dd></div></dl><div class="artifact"><code>{{JSON.stringify(item.lineage,null,2)}}</code></div></article></div><article class="panel"><div class="panel-head"><div><h3>同步规格</h3><p>创建该版本时的不可变输入</p></div></div><div class="artifact"><code>{{JSON.stringify(item.specification,null,2)}}</code></div></article></template></section></template>
<style scoped>.download-card{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:16px 0;padding:18px 20px;border-color:#c8dff7;background:linear-gradient(120deg,#f8fbff,#fff)}.download-card h3{margin:4px 0 6px;color:#304057;font-size:15px}.download-card p{max-width:760px;margin:0;color:#697a8f;font-size:10px;line-height:1.65}.download-card small{display:block;margin-top:7px;color:#3978c8;font-size:9px}.download-card .primary{flex:none;white-space:nowrap}.download-error{margin-top:8px!important;color:#c34e43!important}@media(max-width:720px){.download-card{align-items:stretch;flex-direction:column}.download-card .primary{justify-content:center}}</style>
