<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from './api'
import {authenticated,clearSession,refreshToken,user} from './auth'
import {clearProject,selectProject,selectedProjectId} from './projects'
import {activeFlowSegment,flowSegments} from './sections'
import ToastCenter from './components/ToastCenter.vue'
import {
  Activity,Bell,ChartNoAxesCombined,Check,ChevronDown,FolderKanban,LogOut,Search,
  Settings2,ShieldCheck,Users,X,
} from 'lucide-vue-next'

const route=useRoute(),router=useRouter()
const publicPage=computed(()=>Boolean(route.meta.public))
const projects=ref<any[]>([]),notifications=ref<any[]>([]),jobs=ref<any[]>([])
const searchOpen=ref(false),notificationOpen=ref(false),userMenuOpen=ref(false),searchQuery=ref(''),searchResults=ref<any[]>([]),searching=ref(false)
let refreshTimer:number|undefined

// 顶栏按“获取数据 → 因子 → 训练 → 回测 → 模拟盘”高亮当前段，段内视图交给页签。
const activeSegmentKey=computed(()=>activeFlowSegment(route.path)?.key||'')

watch([publicPage,authenticated],async([isPublic,isAuthenticated])=>{
  if(isPublic||!isAuthenticated){projects.value=[];notifications.value=[];jobs.value=[];return}
  try{
    projects.value=(await api.get('/projects')).data
    if(!projects.value.some(project=>project.id===selectedProjectId.value)){
      if(projects.value.length)selectProject(projects.value[0].id)
      else clearProject()
    }
    await loadOverview()
  }catch{projects.value=[]}
},{immediate:true})

// 顶栏只关心两件事：有没有未读通知、有没有正在跑的任务。刷新失败时保留上一次
// 的数量，具体错误由各页面自己展示，不在顶栏里编数字。
async function loadOverview(){
  if(!authenticated.value||!selectedProjectId.value)return
  try{
    const [notificationResponse,jobResponse]=await Promise.all([api.get('/notifications',{params:{limit:10}}),api.get('/jobs')])
    notifications.value=notificationResponse.data
    jobs.value=Array.isArray(jobResponse.data)?jobResponse.data:(jobResponse.data?.items||[])
  }catch{}
}
const unreadCount=computed(()=>notifications.value.filter(item=>item.status==='open').length)
const runningJobCount=computed(()=>jobs.value.filter(item=>['queued','running','cancel_requested'].includes(item.status)).length)
const governanceNav:readonly [string,string,any][]=[
  ['/projects','项目与成员',FolderKanban],['/admin/users','用户管理',Users],
  ['/admin/audit','审计日志',ShieldCheck],['/monitoring','生产运行',ChartNoAxesCombined],
]
const availableGovernanceNav=computed(()=>user.value?.role==='admin'?governanceNav:[])
function changeProject(id:string){selectProject(id);userMenuOpen.value=false;window.location.reload()}
function closeUserMenu(){userMenuOpen.value=false}
async function logout(){try{if(refreshToken.value)await api.post('/auth/logout',{refresh_token:refreshToken.value})}finally{clearSession();clearProject();router.replace('/login')}}
async function search(){
  if(searchQuery.value.trim().length<2){searchResults.value=[];return}
  searching.value=true
  try{searchResults.value=(await api.get('/search',{params:{q:searchQuery.value.trim(),limit:8}})).data}
  finally{searching.value=false}
}
function openResult(item:any){searchOpen.value=false;searchQuery.value='';searchResults.value=[];router.push(item.url)}
function openNotifications(){notificationOpen.value=!notificationOpen.value;if(notificationOpen.value)loadOverview()}

// 顶栏不再显示页面标题，浏览器标签页继续跟随路由 meta.title。
watch(()=>route.meta.title,title=>{document.title=title?`${String(title)} · QuantForge`:'QuantForge'},{immediate:true})

onMounted(()=>{refreshTimer=window.setInterval(loadOverview,30000);document.addEventListener('click',closeUserMenu)})
onUnmounted(()=>{window.clearInterval(refreshTimer);document.removeEventListener('click',closeUserMenu)})
</script>

<template>
  <RouterView v-if="publicPage"/>
  <div v-else class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <RouterLink class="topbar-brand" to="/" aria-label="返回研究控制台" title="返回研究控制台">
          <span class="brand-mark">Q</span>
          <span class="brand-copy"><strong>QuantForge</strong><small>RESEARCH</small></span>
        </RouterLink>
        <nav class="topbar-nav" aria-label="五段研究流">
          <RouterLink v-for="segment in flowSegments" :key="segment.key" class="nav-pill" :class="{active:activeSegmentKey===segment.key}" :aria-current="activeSegmentKey===segment.key?'page':undefined" :title="segment.label" :to="segment.to"><component :is="segment.icon" :size="16"/><span>{{segment.label}}</span></RouterLink>
        </nav>
        <div class="topbar-actions">
          <button class="icon-btn" aria-label="搜索" title="全局搜索" @click="searchOpen=true"><Search :size="18"/></button>
          <RouterLink class="icon-btn" to="/jobs" aria-label="任务中心" title="任务中心"><Activity :size="18"/><i v-if="runningJobCount" class="icon-badge">{{runningJobCount}}</i></RouterLink>
          <div class="header-popover-anchor"><button class="icon-btn" aria-label="通知" title="通知中心" @click="openNotifications"><Bell :size="18"/><i v-if="unreadCount" class="notification-badge">{{unreadCount}}</i></button><div v-if="notificationOpen" class="header-popover"><div class="popover-head"><b>最新通知</b><button @click="notificationOpen=false"><X :size="14"/></button></div><div v-for="item in notifications.slice(0,5)" :key="item.id" class="popover-item"><i :class="item.severity"></i><div><b>{{item.title}}</b><small>{{item.message}}</small></div></div><div v-if="!notifications.length" class="empty">暂无通知</div><RouterLink to="/notifications" @click="notificationOpen=false">查看全部通知</RouterLink></div></div>
          <div class="user-menu-anchor" @click.stop>
            <button class="avatar-trigger" type="button" aria-label="用户菜单" aria-haspopup="true" :aria-expanded="userMenuOpen" @click="userMenuOpen=!userMenuOpen"><span class="avatar">{{(user?.display_name||'W').slice(0,1)}}</span><ChevronDown :size="15" :class="{open:userMenuOpen}"/></button>
            <div v-if="userMenuOpen" class="user-menu">
              <div class="user-menu-head"><span class="avatar">{{(user?.display_name||'W').slice(0,1)}}</span><div><b>{{user?.display_name||'研究用户'}}</b><small>{{user?.email||'未登录邮箱'}} · {{user?.role||'member'}}</small></div></div>
              <p class="menu-label"><FolderKanban :size="12"/>当前项目</p>
              <button v-for="project in projects" :key="project.id" type="button" class="menu-project" :class="{active:project.id===selectedProjectId}" :title="`切换到项目 ${project.name}`" @click="changeProject(project.id)"><span class="menu-item-copy"><b>{{project.name}}</b><small>{{project.member_role||'member'}} 项目空间</small></span><Check v-if="project.id===selectedProjectId" :size="15"/></button>
              <p v-if="!projects.length" class="menu-empty">还没有可切换的项目，请联系管理员把你加入项目。</p>
              <template v-if="availableGovernanceNav.length">
                <div class="menu-divider"></div>
                <p class="menu-label"><Settings2 :size="12"/>平台治理</p>
                <RouterLink v-for="[to,label,icon] in availableGovernanceNav" :key="to" :to="to" @click="userMenuOpen=false"><component :is="icon" :size="15"/><span>{{label}}</span></RouterLink>
              </template>
              <div class="menu-divider"></div>
              <button type="button" class="menu-logout" @click="logout"><LogOut :size="15"/><span>退出登录</span></button>
            </div>
          </div>
        </div>
      </div>
    </header>
    <main class="app-content"><RouterView/></main>
    <div v-if="searchOpen" class="modal-backdrop" @click.self="searchOpen=false"><section class="search-modal"><div class="search-input"><Search :size="20"/><input v-model="searchQuery" autofocus placeholder="搜索策略、数据、实验、模型或回测" @input="search" @keyup.esc="searchOpen=false"/><button @click="searchOpen=false"><X :size="18"/></button></div><div v-if="searching" class="empty">正在搜索…</div><button v-for="item in searchResults" :key="item.type+item.id" class="search-result" @click="openResult(item)"><span>{{item.type}}</span><div><b>{{item.title}}</b><small>{{item.subtitle}}</small></div></button><div v-if="searchQuery.length>=2&&!searching&&!searchResults.length" class="empty">没有找到匹配资源。</div></section></div>
  </div>
  <ToastCenter/>
</template>

<style scoped>
/* 对齐设计稿的顶栏形状：五段一级入口是圆角 pill，工具按钮 10px 圆角。
   尺寸与配色仍由 topbar.css 定义，这里只做形状微调，不重刷全局色板。 */
.topbar-nav .nav-pill{border-radius:99px;padding:0 15px}
.topbar-actions .icon-btn{border-radius:10px}
@media(max-width:900px){.topbar-nav .nav-pill{padding:0 12px}}
</style>
