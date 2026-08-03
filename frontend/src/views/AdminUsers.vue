<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
import {pushToast} from '../ui'
import Paginator from '../components/Paginator.vue'
import {Plus,RefreshCw,Users} from 'lucide-vue-next'

const rows=ref<any[]>([]),total=ref(0),page=ref(1),loading=ref(false)
const pageSize=20,query=ref(''),role=ref(''),active=ref('')
const form=ref({email:'',display_name:'',password:'',role:'researcher'})
async function load(){
  loading.value=true
  try{
    const response=await api.get('/users',{params:{q:query.value,role:role.value||undefined,active:active.value===''?undefined:active.value==='true',offset:(page.value-1)*pageSize,limit:pageSize}})
    rows.value=response.data;total.value=Number(response.headers['x-total-count']||rows.value.length)
  }finally{loading.value=false}
}
async function create(){
  await api.post('/users',form.value);form.value={email:'',display_name:'',password:'',role:'researcher'}
  pushToast('用户已创建','success');await load()
}
async function update(row:any,changes:any){await api.patch(`/users/${row.id}`,changes);pushToast('用户状态已更新','success');await load()}
function search(){page.value=1;load()}
onMounted(load)
</script>
<template><section><div class="page-intro"><div><h2>用户管理</h2><p>创建平台账号、分配全局角色并控制登录状态</p></div><button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div>
<div class="detail-grid"><article class="panel"><div class="panel-head"><div><h3>创建用户</h3><p>初始密码至少 12 位</p></div><Plus :size="18"/></div><div class="field"><label>邮箱</label><input v-model="form.email" type="email"/></div><div class="field"><label>显示名称</label><input v-model="form.display_name"/></div><div class="field"><label>初始密码</label><input v-model="form.password" type="password"/></div><div class="field"><label>平台角色</label><select v-model="form.role"><option value="researcher">researcher</option><option value="viewer">viewer</option><option value="admin">admin</option></select></div><button class="primary" :disabled="!form.email||form.password.length<12" @click="create"><Users :size="15"/>创建用户</button></article>
<article class="panel"><div class="panel-head"><div><h3>权限说明</h3><p>平台角色与项目角色分开管理</p></div></div><p><b>admin</b>：用户、审计、全局配置与模型审批。</p><p><b>researcher</b>：项目内数据、训练、回测和预测。</p><p><b>viewer</b>：用于只读协作成员。</p></article></div>
<article class="panel"><div class="toolbar"><label><input v-model="query" placeholder="搜索邮箱或名称" @keyup.enter="search"/></label><select v-model="role" @change="search"><option value="">全部角色</option><option value="admin">admin</option><option value="researcher">researcher</option><option value="viewer">viewer</option></select><select v-model="active" @change="search"><option value="">全部状态</option><option value="true">启用</option><option value="false">停用</option></select><button class="secondary" @click="search">筛选</button></div><div class="data-table"><div class="data-row header with-action"><span>用户</span><span>平台角色</span><span>状态</span><span>创建时间</span><span>操作</span></div><div v-for="row in rows" :key="row.id" class="data-row with-action"><span>{{row.display_name}}<small>{{row.email}}</small></span><span><select :value="row.role" @change="update(row,{role:($event.target as HTMLSelectElement).value})"><option value="admin">admin</option><option value="researcher">researcher</option><option value="viewer">viewer</option></select></span><span><i class="status" :class="row.is_active?'succeeded':'archived'">{{row.is_active?'active':'disabled'}}</i></span><span>{{new Date(row.created_at).toLocaleString()}}</span><span><button class="text-button" @click="update(row,{is_active:!row.is_active})">{{row.is_active?'停用':'启用'}}</button></span></div></div><Paginator :page="page" :total="total" :page-size="pageSize" @change="value=>{page=value;load()}"/></article></section></template>
