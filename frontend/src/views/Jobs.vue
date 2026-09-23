<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
import {token} from '../auth'
import {jobKindLabel,jobSectionLabel,jobTarget} from '../jobs'
import {selectedProjectId} from '../projects'
import StatusBadge from '../components/StatusBadge.vue'
import {statusLabel} from '../status'
import {ChevronRight,ExternalLink,RefreshCw,RotateCcw,Square} from 'lucide-vue-next'

// 任务中心是工具窗口：所有后台计算统一在这里看。任务类型说中文、失败原因说人话、
// 完成的任务直接给出产出物落点，用户不需要知道 kind 枚举是什么。
const statusOptions=['queued','running','succeeded','failed','canceled']
const rows=ref<any[]>([]),loading=ref(false),acting=ref(''),error=ref(''),realtime=ref(false),statusFilter=ref('')
const expanded=ref<string[]>([])
const visible=computed(()=>rows.value.filter(job=>!statusFilter.value||job.status===statusFilter.value))
const runningCount=computed(()=>rows.value.filter(job=>['queued','running','cancel_requested'].includes(job.status)).length)
const failedCount=computed(()=>rows.value.filter(job=>job.status==='failed').length)
let timer:number|undefined,socket:WebSocket|undefined

async function load(silent=false){if(!silent)loading.value=true;try{rows.value=(await api.get('/jobs')).data}finally{loading.value=false}}
async function action(job:any,name:'cancel'|'retry'){acting.value=job.id;error.value='';try{await api.post(`/jobs/${job.id}/${name}`);await load(true)}catch(e:any){error.value=e.response?.data?.detail||e.message}finally{acting.value=''}}
function toggleReason(id:string){expanded.value=expanded.value.includes(id)?expanded.value.filter(item=>item!==id):[...expanded.value,id]}
function connect(){const base=String(api.defaults.baseURL).replace(/^http/,'ws');const project=selectedProjectId.value?`&project_id=${encodeURIComponent(selectedProjectId.value)}`:'';socket=new WebSocket(`${base}/ws/jobs?token=${encodeURIComponent(token.value)}${project}`);socket.onopen=()=>realtime.value=true;socket.onmessage=event=>rows.value=JSON.parse(event.data);socket.onclose=()=>realtime.value=false;socket.onerror=()=>socket?.close()}
onMounted(()=>{load();connect();timer=window.setInterval(()=>{if(!realtime.value)load(true)},3000)});onUnmounted(()=>{window.clearInterval(timer);socket?.close()})
</script>

<template><section><div class="page-intro"><div><h2>任务中心</h2><p>所有后台计算都在这里：失败原因看得懂，完成的任务直达产出物</p></div><button class="secondary" @click="load()"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><p v-if="error" class="error-box">{{error}}</p><article class="panel records"><div class="toolbar"><label><span>状态筛选</span><select v-model="statusFilter"><option value="">全部状态</option><option v-for="value in statusOptions" :key="value" :value="value">{{statusLabel(value)}}</option></select></label><span class="toolbar-count">运行中 {{runningCount}} · 失败 {{failedCount}} · 显示 {{visible.length}} / {{rows.length}} 个任务<i class="live" :class="{on:realtime}">{{realtime?'实时推送':'轮询刷新'}}</i></span></div><div class="data-table"><div class="job-row job-header"><span>类型 / 所属段</span><span>状态</span><span>进度</span><span>失败原因</span><span>创建时间</span><span>操作</span></div><div class="job-row" v-for="job in visible" :key="job.id"><span class="job-identity"><b>{{jobKindLabel(job.kind)}}</b><small><i class="section-chip">{{jobSectionLabel(job.kind)}}</i>{{job.worker_name||'等待计算节点'}}</small></span><span><StatusBadge :status="job.status"/></span><span><div class="bar"><i :style="{width:job.progress+'%'}"></i></div><small>{{job.progress}}%</small></span><span v-if="job.status==='failed'" class="failure-cell"><button type="button" class="failure-toggle" :class="{open:expanded.includes(job.id)}" :aria-expanded="expanded.includes(job.id)" :title="job.error_message||'未记录失败原因'" @click="toggleReason(job.id)"><ChevronRight :size="13"/><span>{{job.error_message||'未记录失败原因'}}</span></button></span><span v-else class="muted-cell">—</span><span class="time-cell">{{new Date(job.created_at).toLocaleString('zh-CN')}}</span><span class="row-actions"><RouterLink v-if="job.status==='succeeded'&&jobTarget(job)" class="text-button" :to="jobTarget(job)!.to"><ExternalLink :size="13"/>{{jobTarget(job)!.label}}</RouterLink><button v-if="['queued','running'].includes(job.status)" class="text-button danger" :disabled="acting===job.id" @click="action(job,'cancel')"><Square :size="13"/>取消</button><button v-if="['failed','canceled'].includes(job.status)" class="text-button" :disabled="acting===job.id" @click="action(job,'retry')"><RotateCcw :size="13"/>重试</button></span></div><div v-if="!visible.length&&!loading" class="empty">{{statusFilter?'该状态下没有任务，切换筛选或查看全部任务。':'暂无任务。同步数据、训练模型或运行回测后，任务会实时出现在这里。'}}</div></div></article></section></template>

<style scoped>
.toolbar label{height:38px}.toolbar select{border:0;background:transparent;color:#34445a;font-size:13px;font-weight:600;outline:0}.toolbar-count{display:flex;align-items:center;gap:9px;color:#8b97a7;font-size:11px}
.live{font-style:normal;padding:2px 8px;border-radius:99px;background:#eef0f4;color:#7c8999;font-size:10px}
.live.on{background:#e4f8f1;color:#16845f}
.section-chip{margin-right:6px;padding:1px 7px;border-radius:99px;background:#f0eafe;color:#7451ca;font-style:normal;font-size:9px;font-weight:700}
.failure-cell{min-width:0}
.failure-toggle{display:flex;align-items:flex-start;gap:4px;width:100%;padding:0;border:0;background:none;color:#c3494f;font-size:11px;text-align:left}
.failure-toggle svg{margin-top:2px;flex:none;transition:transform .16s ease}
.failure-toggle.open svg{transform:rotate(90deg)}
.failure-toggle>span{flex:1;min-width:0;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.failure-toggle.open>span{-webkit-line-clamp:unset;overflow:visible}
.time-cell{color:#526176;font-size:11px}
.row-actions{flex-wrap:wrap}
.row-actions a.text-button{text-decoration:none}
.row-actions a.text-button:hover{text-decoration:underline}
</style>
