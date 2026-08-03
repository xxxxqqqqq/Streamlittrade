<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
import {user} from '../auth'
import {Bell,CheckCircle2,RefreshCw} from 'lucide-vue-next'
const rows=ref<any[]>([]),status=ref(''),loading=ref(false)
async function load(){loading.value=true;try{rows.value=(await api.get('/notifications',{params:{status:status.value||undefined,limit:100}})).data}finally{loading.value=false}}
async function update(row:any,value:string){await api.patch(`/monitoring/alerts/${row.id}`,{status:value});await load()}onMounted(load)
</script>
<template><section><div class="page-intro"><div><h2>通知中心</h2><p>模型漂移、自动任务阻塞和生产运行事件</p></div><button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><article class="panel"><div class="toolbar"><select v-model="status" @change="load"><option value="">全部通知</option><option value="open">未处理</option><option value="acknowledged">已确认</option><option value="resolved">已解决</option></select></div><div v-if="!rows.length" class="all-clear"><CheckCircle2 :size="22"/><div><b>当前没有通知</b><small>生产运行状态正常</small></div></div><div v-for="row in rows" :key="row.id" class="notification-row" :class="[row.severity,row.status]"><Bell :size="18"/><div><b>{{row.title}}</b><span>{{row.message}}</span><small>{{new Date(row.created_at).toLocaleString()}} · {{row.status}}</small></div><div v-if="user?.role==='admin'&&row.status!=='resolved'" class="row-actions"><button v-if="row.status==='open'" class="text-button" @click="update(row,'acknowledged')">确认</button><button class="text-button" @click="update(row,'resolved')">解决</button></div></div></article></section></template>
