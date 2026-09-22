<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
import {token} from '../auth'
import {selectedProjectId} from '../projects'
import StatusBadge from '../components/StatusBadge.vue'
import {statusLabel} from '../status'
import {RefreshCw,RotateCcw,Square} from 'lucide-vue-next'

const statusOptions=['queued','running','succeeded','failed','canceled']
const rows=ref<any[]>([]),loading=ref(false),acting=ref(''),error=ref(''),realtime=ref(false),statusFilter=ref('')
const visible=computed(()=>rows.value.filter(job=>!statusFilter.value||job.status===statusFilter.value))
let timer:number|undefined,socket:WebSocket|undefined
async function load(silent=false){if(!silent)loading.value=true;try{rows.value=(await api.get('/jobs')).data}finally{loading.value=false}}
async function action(job:any,name:'cancel'|'retry'){acting.value=job.id;error.value='';try{await api.post(`/jobs/${job.id}/${name}`);await load(true)}catch(e:any){error.value=e.response?.data?.detail||e.message}finally{acting.value=''}}
function connect(){const base=String(api.defaults.baseURL).replace(/^http/,'ws');const project=selectedProjectId.value?`&project_id=${encodeURIComponent(selectedProjectId.value)}`:'';socket=new WebSocket(`${base}/ws/jobs?token=${encodeURIComponent(token.value)}${project}`);socket.onopen=()=>realtime.value=true;socket.onmessage=event=>rows.value=JSON.parse(event.data);socket.onclose=()=>realtime.value=false;socket.onerror=()=>socket?.close()}
onMounted(()=>{load();connect();timer=window.setInterval(()=>{if(!realtime.value)load(true)},3000)});onUnmounted(()=>{window.clearInterval(timer);socket?.close()})
</script>

<template><section><div class="page-intro"><div><h2>任务中心</h2><p>实时监控、取消和重新执行研究任务</p></div><button class="secondary" @click="load()"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><p v-if="error" class="error-box">{{error}}</p><article class="panel records"><div class="toolbar"><label><span>状态筛选</span><select v-model="statusFilter"><option value="">全部状态</option><option v-for="value in statusOptions" :key="value" :value="value">{{statusLabel(value)}}</option></select></label><span class="toolbar-count">显示 {{visible.length}} / {{rows.length}} 个任务</span></div><div class="data-table"><div class="job-row job-header"><span>类型 / 计算节点</span><span>状态</span><span>进度</span><span>失败原因</span><span>创建时间</span><span>操作</span></div><div class="job-row" v-for="job in visible" :key="job.id"><span class="job-identity"><b>{{job.kind}}</b><small>{{job.queue_name||'legacy'}} · {{job.worker_name||'等待节点'}}</small></span><span><StatusBadge :status="job.status"/></span><span><div class="bar"><i :style="{width:job.progress+'%'}"></i></div><small>{{job.progress}}%</small></span><span v-if="job.status==='failed'" class="failure-reason" :title="job.error_message||'未记录失败原因'">{{job.error_message||'未记录失败原因'}}</span><span v-else class="muted-cell">—</span><span>{{new Date(job.created_at).toLocaleString()}}</span><span class="row-actions"><button v-if="['queued','running'].includes(job.status)" class="text-button danger" :disabled="acting===job.id" @click="action(job,'cancel')"><Square :size="13"/>取消</button><button v-if="['failed','canceled'].includes(job.status)" class="text-button" :disabled="acting===job.id" @click="action(job,'retry')"><RotateCcw :size="13"/>重试</button></span></div><div v-if="!visible.length&&!loading" class="empty">{{statusFilter?'该状态下没有任务，切换筛选或查看全部任务。':'暂无任务。同步数据、训练模型或运行回测后，任务会实时出现在这里。'}}</div></div></article></section></template>

<style scoped>
.toolbar label{height:38px}.toolbar select{border:0;background:transparent;color:#34445a;font-size:13px;font-weight:600;outline:0}.toolbar-count{color:#8b97a7;font-size:11px}.failure-reason{display:block;overflow:hidden;color:#c3494f;text-overflow:ellipsis;white-space:nowrap}.muted-cell{color:#a1adbb}
</style>
