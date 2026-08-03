<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {api} from '../api'
import {Plus,RefreshCw,ScrollText} from 'lucide-vue-next'

const rows=ref<any[]>([])
const loading=ref(false)
const saving=ref(false)
const error=ref('')
const form=ref({
  name:'右侧趋势策略',
  slug:'right-trend',
  implementation:'right_trend',
  description:'均线多头、量价确认的右侧趋势策略',
  ma_short:5,ma_mid:20,ma_long:60,vol_ratio:1.5,
  lookback:10,drop_threshold:0.08,rebound_threshold:0.03,confirm_days:2,
})
const isTrend=computed(()=>form.value.implementation==='right_trend')

async function load(){
  loading.value=true
  try{rows.value=(await api.get('/strategies')).data}
  finally{loading.value=false}
}

async function create(){
  saving.value=true
  error.value=''
  try{
    const parameters=isTrend.value
      ? {ma_short:Number(form.value.ma_short),ma_mid:Number(form.value.ma_mid),ma_long:Number(form.value.ma_long),vol_ratio:Number(form.value.vol_ratio)}
      : {lookback:Number(form.value.lookback),drop_threshold:Number(form.value.drop_threshold),rebound_threshold:Number(form.value.rebound_threshold),confirm_days:Number(form.value.confirm_days),vol_ratio:Number(form.value.vol_ratio)}
    await api.post('/strategies',{
      name:form.value.name,
      slug:form.value.slug,
      implementation:form.value.implementation,
      description:form.value.description,
      parameters,
    })
    await load()
  }catch(exception:any){
    error.value=exception.response?.data?.detail||exception.message
  }finally{saving.value=false}
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-intro">
      <div><h2>策略版本管理</h2><p>平台审核过的内置实现与不可变参数版本</p></div>
      <button class="secondary" @click="load"><RefreshCw :size="16" :class="{spin:loading}"/>刷新</button>
    </div>
    <p v-if="error" class="error-box">{{error}}</p>
    <div class="detail-grid">
      <article class="panel">
        <div class="panel-head"><div><h3>创建策略版本</h3><p>相同标识会自动生成下一版本</p></div><Plus :size="19"/></div>
        <div class="field"><label>名称</label><input v-model="form.name"/></div>
        <div class="field"><label>稳定标识</label><input v-model="form.slug"/></div>
        <div class="field"><label>平台实现</label><select v-model="form.implementation"><option value="right_trend">右侧趋势</option><option value="v_shape">V型反转</option></select></div>
        <div class="field"><label>说明</label><input v-model="form.description"/></div>
        <div v-if="isTrend" class="form-grid">
          <div class="field"><label>短期均线</label><input v-model.number="form.ma_short" type="number"/></div>
          <div class="field"><label>中期均线</label><input v-model.number="form.ma_mid" type="number"/></div>
          <div class="field"><label>长期均线</label><input v-model.number="form.ma_long" type="number"/></div>
          <div class="field"><label>量比</label><input v-model.number="form.vol_ratio" type="number" step="0.1"/></div>
        </div>
        <div v-else class="form-grid">
          <div class="field"><label>回看周期</label><input v-model.number="form.lookback" type="number"/></div>
          <div class="field"><label>下跌阈值</label><input v-model.number="form.drop_threshold" type="number" step="0.01"/></div>
          <div class="field"><label>反弹阈值</label><input v-model.number="form.rebound_threshold" type="number" step="0.01"/></div>
          <div class="field"><label>确认天数</label><input v-model.number="form.confirm_days" type="number"/></div>
        </div>
        <button class="primary" :disabled="saving" @click="create"><Plus :size="15"/>{{saving?'正在保存':'登记新版本'}}</button>
      </article>
      <article class="panel">
        <div class="panel-head"><div><h3>版本使用规则</h3><p>回测绑定具体策略 ID</p></div><ScrollText :size="19"/></div>
        <p>修改参数不会覆盖历史策略；使用相同 slug 提交时生成 v2、v3 等新版本。</p>
        <p>回测记录同时保存策略版本 ID、实现名称和参数快照，可重复执行。</p>
      </article>
    </div>
    <article class="panel">
      <div class="data-table">
        <div class="data-row header"><span>名称</span><span>标识 / 版本</span><span>实现</span><span>参数</span></div>
        <div v-for="row in rows" :key="row.id" class="data-row">
          <span>{{row.name}}</span><span>{{row.slug}} v{{row.version}}</span><span>{{row.implementation}}</span><span>{{JSON.stringify(row.parameters)}}</span>
        </div>
        <div v-if="!rows.length&&!loading" class="empty">尚未登记策略版本。</div>
      </div>
    </article>
  </section>
</template>
