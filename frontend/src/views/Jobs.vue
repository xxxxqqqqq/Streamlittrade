<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
import {token} from '../auth'
import {selectedProjectId} from '../projects'
import {RefreshCw,RotateCcw,Square} from 'lucide-vue-next'

const rows=ref<any[]>([]),loading=ref(false),acting=ref(''),error=ref(''),realtime=ref(false);let timer:number|undefined,socket:WebSocket|undefined
async function load(silent=false){if(!silent)loading.value=true;try{rows.value=(await api.get('/jobs')).data}finally{loading.value=false}}
async function action(job:any,name:'cancel'|'retry'){acting.value=job.id;error.value='';try{await api.post(`/jobs/${job.id}/${name}`);await load(true)}catch(e:any){error.value=e.response?.data?.detail||e.message}finally{acting.value=''}}
function connect(){const base=String(api.defaults.baseURL).replace(/^http/,'ws');const project=selectedProjectId.value?`&project_id=${encodeURIComponent(selectedProjectId.value)}`:'';socket=new WebSocket(`${base}/ws/jobs?token=${encodeURIComponent(token.value)}${project}`);socket.onopen=()=>realtime.value=true;socket.onmessage=event=>rows.value=JSON.parse(event.data);socket.onclose=()=>realtime.value=false;socket.onerror=()=>socket?.close()}
onMounted(()=>{load();connect();timer=window.setInterval(()=>{if(!realtime.value)load(true)},3000)});onUnmounted(()=>{window.clearInterval(timer);socket?.close()})
</script>

<template><section><div class="page-intro"><div><h2>计算任务</h2><p>实时监控、取消和重新执行研究任务</p></div><button class="secondary" @click="load()"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><p v-if="error" class="error-box">{{error}}</p><article class="panel records"><div class="data-table"><div class="job-row job-header"><span>类型</span><span>状态</span><span>进度</span><span>创建时间</span><span>操作</span></div><div class="job-row" v-for="job in rows" :key="job.id"><b>{{job.kind}}</b><span><i class="status" :class="job.status">{{job.status}}</i></span><span><div class="bar"><i :style="{width:job.progress+'%'}"></i></div><small>{{job.progress}}%</small></span><span>{{new Date(job.created_at).toLocaleString()}}</span><span class="row-actions"><button v-if="['queued','running'].includes(job.status)" class="text-button danger" :disabled="acting===job.id" @click="action(job,'cancel')"><Square :size="13"/>取消</button><button v-if="['failed','canceled'].includes(job.status)" class="text-button" :disabled="acting===job.id" @click="action(job,'retry')"><RotateCcw :size="13"/>重试</button></span></div><div v-if="!rows.length&&!loading" class="empty">暂无任务。</div></div></article></section></template>
