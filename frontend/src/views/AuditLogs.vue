<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
import Paginator from '../components/Paginator.vue'
import {RefreshCw,Search} from 'lucide-vue-next'
const rows=ref<any[]>([]),total=ref(0),page=ref(1),loading=ref(false),q=ref(''),type=ref('')
const pageSize=25
async function load(){loading.value=true;try{const response=await api.get('/audit-logs',{params:{q:q.value,resource_type:type.value||undefined,offset:(page.value-1)*pageSize,limit:pageSize}});rows.value=response.data;total.value=Number(response.headers['x-total-count']||rows.value.length)}finally{loading.value=false}}
function search(){page.value=1;load()}onMounted(load)
</script>
<template><section><div class="page-intro"><div><h2>审计日志</h2><p>安全操作、模型生命周期与成员变更的不可变记录</p></div><button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><article class="panel"><div class="toolbar"><label><Search :size="16"/><input v-model="q" placeholder="搜索动作、资源或 ID" @keyup.enter="search"/></label><select v-model="type" @change="search"><option value="">全部资源</option><option value="user">user</option><option value="project">project</option><option value="model">model</option><option value="alert">alert</option><option value="paper_order">paper_order</option></select><button class="secondary" @click="search">筛选</button></div><div class="data-table"><div class="data-row header"><span>时间</span><span>动作</span><span>资源</span><span>详情</span></div><div v-for="row in rows" :key="row.id" class="data-row"><span>{{new Date(row.created_at).toLocaleString()}}</span><code>{{row.action}}</code><span>{{row.resource_type}}<small>{{row.resource_id}}</small></span><code>{{JSON.stringify(row.details).slice(0,120)}}</code></div></div><Paginator :page="page" :total="total" :page-size="pageSize" @change="value=>{page=value;load()}"/></article></section></template>
