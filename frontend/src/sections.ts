import type {Component} from 'vue'
import {BrainCircuit,Filter,FlaskConical,Layers3,WalletCards} from 'lucide-vue-next'

// 顶栏五段流与各段页签的唯一来源：App.vue 用它渲染一级入口，各段页面用同一
// 份定义渲染页签，避免顶栏、页签和路由标题对同一功能给出三种叫法。
export interface FlowSegment{key:string;label:string;to:string;paths:readonly string[];icon:Component}
export interface SectionTab{label:string;to:string;query?:Record<string,string>}

export const flowSegments:readonly FlowSegment[]=[
  {key:'data',label:'获取数据',to:'/data-center',paths:['/data-center'],icon:Layers3},
  {key:'factor',label:'因子',to:'/factor-research',paths:['/factor-research'],icon:Filter},
  {key:'train',label:'训练',to:'/experiments',paths:['/datasets','/experiments','/models'],icon:BrainCircuit},
  {key:'backtest',label:'回测',to:'/backtests',paths:['/backtests','/strategies','/predictions'],icon:FlaskConical},
  {key:'paper',label:'模拟盘',to:'/paper',paths:['/paper'],icon:WalletCards},
]

// 数据段与因子段共用“因子快照”视图：快照是数据中心的产物，用 query 定位到页内
// 快照区，而不是为同一张表再造一个路由。
export const dataTabs:readonly SectionTab[]=[
  {label:'数据同步与版本',to:'/data-center'},
  {label:'因子快照',to:'/data-center',query:{focus:'snapshots'}},
]
export const factorTabs:readonly SectionTab[]=[
  {label:'因子研究',to:'/factor-research'},
]
export const trainingTabs:readonly SectionTab[]=[
  {label:'训练实验',to:'/experiments'},
  {label:'研究数据集',to:'/datasets'},
  {label:'模型仓库',to:'/models'},
  {label:'模型比较',to:'/models/compare'},
]
export const backtestTabs:readonly SectionTab[]=[
  {label:'回测中心',to:'/backtests'},
  {label:'策略版本',to:'/strategies'},
  {label:'批量预测',to:'/predictions'},
]
export const paperTabs:readonly SectionTab[]=[
  {label:'账户总览',to:'/paper'},
  {label:'自动调仓',to:'/paper',query:{tab:'automation'}},
]

// 页签高亮按最长路径前缀判定：/models/compare 命中“模型比较”，/models/:id 落回
// “模型仓库”；带 query 的页签优先，避免同路径页签互相抢高亮。
export function activeSectionTab(path:string,query:Record<string,unknown>,tabs:readonly SectionTab[]){
  let matched:SectionTab|null=null,best=-1
  for(const tab of tabs){
    if(path!==tab.to&&!path.startsWith(`${tab.to}/`))continue
    if(tab.query&&!Object.entries(tab.query).every(([key,value])=>String(query[key]??'')===value))continue
    const score=tab.to.length+(tab.query?1:0)
    if(score>best){matched=tab;best=score}
  }
  return matched
}

export function activeFlowSegment(path:string,segments:readonly FlowSegment[]=flowSegments){
  return segments.find(segment=>segment.paths.some(prefix=>path===prefix||path.startsWith(`${prefix}/`)))||null
}
