<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
import {selectedProjectId,selectProject} from '../projects'
import {pushToast} from '../ui'
import {FolderPlus,RefreshCw,UserPlus} from 'lucide-vue-next'

const projects=ref<any[]>([]),members=ref<any[]>([]),users=ref<any[]>([])
const projectForm=ref({name:'',slug:''}),memberForm=ref({user_id:'',role:'researcher'}),loading=ref(false)
async function load(){
  loading.value=true
  try{
    const [projectResponse,userResponse]=await Promise.all([api.get('/projects'),api.get('/users',{params:{limit:200}})])
    projects.value=projectResponse.data;users.value=userResponse.data
    if(selectedProjectId.value)members.value=(await api.get(`/projects/${selectedProjectId.value}/members`)).data
  }finally{loading.value=false}
}
async function createProject(){const created=(await api.post('/projects',projectForm.value)).data;selectProject(created.id);pushToast('项目已创建','success');window.location.reload()}
async function addMember(){await api.post(`/projects/${selectedProjectId.value}/members`,memberForm.value);pushToast('成员已添加','success');await load()}
async function role(member:any,role:string){await api.patch(`/projects/${selectedProjectId.value}/members/${member.id}`,{role});await load()}
async function remove(member:any){await api.delete(`/projects/${selectedProjectId.value}/members/${member.id}`);pushToast('成员已移除','success');await load()}
onMounted(load)
</script>
<template><section><div class="page-intro"><div><h2>项目与成员</h2><p>项目是数据、模型、任务和告警的隔离边界</p></div><button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button></div><div class="detail-grid"><article class="panel"><div class="panel-head"><div><h3>创建项目</h3><p>创建者自动成为 owner</p></div><FolderPlus :size="18"/></div><div class="field"><label>项目名称</label><input v-model="projectForm.name"/></div><div class="field"><label>项目标识</label><input v-model="projectForm.slug" placeholder="alpha-research"/></div><button class="primary" :disabled="!projectForm.name||!projectForm.slug" @click="createProject">创建并切换</button></article><article class="panel"><div class="panel-head"><div><h3>添加当前项目成员</h3><p>成员必须先拥有平台账号</p></div><UserPlus :size="18"/></div><div class="field"><label>用户</label><select v-model="memberForm.user_id"><option value="">选择用户</option><option v-for="item in users.filter(user=>!members.some(member=>member.user_id===user.id))" :key="item.id" :value="item.id">{{item.display_name}} · {{item.email}}</option></select></div><div class="field"><label>项目角色</label><select v-model="memberForm.role"><option value="admin">admin</option><option value="researcher">researcher</option><option value="viewer">viewer</option></select></div><button class="primary" :disabled="!memberForm.user_id" @click="addMember">添加成员</button></article></div>
<article class="panel"><div class="panel-head"><div><h3>当前项目成员</h3><p>{{projects.find(item=>item.id===selectedProjectId)?.name}}</p></div></div><div class="data-table"><div class="data-row header with-action"><span>成员</span><span>项目角色</span><span>加入时间</span><span>用户 ID</span><span>操作</span></div><div v-for="member in members" :key="member.id" class="data-row with-action"><span>{{member.display_name}}<small>{{member.email}}</small></span><span><select :value="member.role" :disabled="projects.find(item=>item.id===selectedProjectId)?.owner_id===member.user_id" @change="role(member,($event.target as HTMLSelectElement).value)"><option value="admin">admin</option><option value="researcher">researcher</option><option value="viewer">viewer</option><option v-if="member.role==='owner'" value="owner">owner</option></select></span><span>{{new Date(member.created_at).toLocaleString()}}</span><code>{{member.user_id.slice(0,8)}}</code><span><button class="text-button" :disabled="projects.find(item=>item.id===selectedProjectId)?.owner_id===member.user_id" @click="remove(member)">移除</button></span></div></div></article></section></template>
