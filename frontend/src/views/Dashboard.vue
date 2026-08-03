<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api,rootApi} from '../api'
import {
  Activity,ArrowRight,Boxes,BrainCircuit,ChartNoAxesCombined,Database,
  Filter,FlaskConical,Layers3,ScrollText,
} from 'lucide-vue-next'

const loading=ref(true),online=ref(false)
const counts=ref({datasets:0,experiments:0,models:0,backtests:0})
const jobs=ref<any[]>([])

// 首页只汇总核心研究产物。任务、监控和治理信息放在下方，不再与
// “取数据—做因子—训模型—做回测”的主流程争夺视觉层级。
onMounted(async()=>{
  try{
    const [health,datasets,experiments,models,backtests,allJobs]=await Promise.all([
      rootApi.get('/health/ready'),api.get('/datasets'),api.get('/experiments'),
      api.get('/models'),api.get('/backtests'),api.get('/jobs'),
    ])
    online.value=health.data.status==='ready'
    counts.value={
      datasets:datasets.data.length,experiments:experiments.data.length,
      models:models.data.length,backtests:backtests.data.length,
    }
    jobs.value=allJobs.data.slice(0,5)
  }finally{loading.value=false}
})

const flow=[
  {step:'01',title:'数据与标的',note:'确定股票池、同步行情，并通过数据质量门禁',to:'/data-center',action:'准备研究数据',icon:Layers3,tone:'tone-blue'},
  {step:'02',title:'因子工程',note:'定义因子、生成快照，检验有效性和稳定性',to:'/factor-research',action:'研究候选因子',icon:Filter,tone:'tone-cyan'},
  {step:'03',title:'研究数据集',note:'固化因子、标签、预测周期与完整数据血缘',to:'/datasets',action:'构建训练样本',icon:Database,tone:'tone-green'},
  {step:'04',title:'模型研究',note:'训练多种算法并完成时间隔离的样本外评估',to:'/experiments',action:'训练与筛选模型',icon:BrainCircuit,tone:'tone-purple'},
  {step:'05',title:'组合回测',note:'把样本外预测转成持仓，检验成本、收益与回撤',to:'/backtests',action:'验证交易表现',icon:FlaskConical,tone:'tone-amber'},
] as const

const metrics=[
  ['研究数据集','datasets',Database],['训练实验','experiments',BrainCircuit],
  ['模型版本','models',Boxes],['回测报告','backtests',FlaskConical],
] as const

const analysisLinks=[
  {title:'模型仓库',note:'查看候选与生产模型版本',to:'/models',icon:Boxes},
  {title:'模型比较',note:'横向分析算法和经济指标',to:'/models/compare',icon:ChartNoAxesCombined},
  {title:'规则策略',note:'管理不依赖机器学习的策略版本',to:'/strategies',icon:ScrollText},
]
</script>

<template>
  <section>
    <div class="hero research-hero">
      <div><span class="eyebrow">CORE RESEARCH WORKFLOW</span><h2>从研究数据到可交易组合，沿五个阶段推进</h2><p>数据版本、因子快照、训练样本、样本外预测和回测报告逐级关联，全程可复现。</p></div>
      <div class="system-pill" :class="{online}"><span></span>{{online?'研究服务正常':'正在连接服务'}}</div>
    </div>

    <div class="flow-heading"><div><h3>核心研究流程</h3><p>建议按顺序完成；每一步的产物会自动成为下一步的输入。</p></div><b>主流程</b></div>
    <div class="core-flow">
      <RouterLink v-for="item in flow" :key="item.step" :to="item.to" class="flow-card" :class="item.tone">
        <div class="flow-card-top"><span>{{item.step}}</span><div class="flow-icon"><component :is="item.icon" :size="22"/></div></div>
        <h3>{{item.title}}</h3><p>{{item.note}}</p>
        <div class="flow-action">{{item.action}}<ArrowRight :size="15"/></div>
      </RouterLink>
    </div>

    <div class="metric-grid compact-metrics">
      <article v-for="[label,key,icon] in metrics" :key="key" class="metric">
        <div class="metric-icon"><component :is="icon" :size="20"/></div>
        <div><small>{{label}}</small><strong>{{loading?'—':counts[key]}}</strong></div>
      </article>
    </div>

    <div class="dashboard-grid">
      <article class="panel wide">
        <div class="panel-head"><div><h3>最近计算任务</h3><p>仅用于确认后台计算状态，不属于研究步骤</p></div><RouterLink to="/jobs">进入任务中心</RouterLink></div>
        <div class="table"><div class="tr th"><span>任务类型</span><span>状态</span><span>进度</span><span>创建时间</span></div><div class="tr" v-for="job in jobs" :key="job.id"><b>{{job.kind}}</b><span><i class="status" :class="job.status">{{job.status}}</i></span><span><div class="bar"><i :style="{width:job.progress+'%'}"></i></div></span><span>{{new Date(job.created_at).toLocaleString()}}</span></div><div v-if="!jobs.length&&!loading" class="empty">暂无计算任务，请从“获取数据”开始。</div></div>
      </article>

      <article class="panel secondary-analysis">
        <div class="panel-head"><div><h3>扩展分析</h3><p>按需使用，不影响核心研究闭环</p></div><Activity :size="18"/></div>
        <RouterLink v-for="item in analysisLinks" :key="item.to" :to="item.to" class="analysis-link">
          <div><component :is="item.icon" :size="17"/></div><span><b>{{item.title}}</b><small>{{item.note}}</small></span><ArrowRight :size="14"/>
        </RouterLink>
      </article>
    </div>
  </section>
</template>
