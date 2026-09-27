<template>
  <section class="page" data-module="cable">
    <header class="page-head">
      <div>
        <h2>电缆线路管理</h2>
        <p class="page-desc">维护电缆段，围绕电缆编号、电缆型号、起止位置、敷设方式做登记、筛选与状态流转；绝缘电阻按判定规则给出正常、关注或需处理结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电缆段</button>
        <button class="btn" type="button" @click="toggleRules">判定规则</button>
        <button class="btn" type="button" @click="exportRows">导出电缆线路清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="showRules" class="rule-panel">
      <h3 class="panel-title">绝缘电阻判定规则</h3>
      <p class="panel-desc">规则按电缆型号或起止位置匹配；同一电缆段命中多条规则时，生效日期不晚于测试日期且最近的一条优先。低于绝缘下限或变化比例超出范围即判定需处理。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ruleColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in rules" :key="String(rule.id)">
            <td v-for="column in ruleColumns" :key="column">{{ rule[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!rules.length">
            <td :colspan="ruleColumns.length" class="empty-state">暂无判定规则，请在下方新增</td>
          </tr>
        </tbody>
      </table>
      <form class="filter-bar rule-form" @submit.prevent="submitRule">
        <label v-for="field in ruleFormFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input
            v-model="ruleForm[field]"
            :placeholder="rulePlaceholders[field] ?? `填写${field}`"
          />
        </label>
        <button class="btn primary" type="submit">新增规则</button>
      </form>
      <p v-if="ruleMessage" class="error-text">{{ ruleMessage }}</p>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '判定结论'" class="judge-badge" :class="judgeClass(row[column])">
              {{ row[column] ?? '—' }}
            </span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无电缆线路数据，可先登记电缆段</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电缆线路记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="dialog-mask" @click.self="closeDetail">
      <section class="dialog">
        <header class="dialog-head">
          <h3>电缆段详情 · {{ detail['电缆编号'] ?? '' }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>
              <span v-if="field === '判定结论'" class="judge-badge" :class="judgeClass(detail[field])">
                {{ detail[field] ?? '—' }}
              </span>
              <template v-else>{{ formatDetail(field, detail[field]) }}</template>
            </dd>
          </template>
        </dl>
        <p class="panel-desc">判定由后端统一计算，与本页列表中的结论同源。</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/cable'
const columns = ["电缆编号", "电缆型号", "起止位置", "敷设方式", "绝缘电阻", "上次测值", "测试日期", "电缆状态", "判定结论"]
const actions = ["测试绝缘", "标记隐患", "安排修复"]
const statuses = ["正常运行", "绝缘降低", "待修复", "已修复"]
const detailFields = ["电缆编号", "电缆型号", "起止位置", "敷设方式", "绝缘电阻", "上次测值", "测试日期", "电缆状态", "判定结论", "适用规则", "变化比例", "判定说明"]
const ruleColumns = ["规则编号", "电缆型号", "起止位置", "生效日期", "绝缘下限", "关注倍数", "变化比例上限", "变化关注比例"]
const ruleFormFields = ["规则编号", "电缆型号", "起止位置", "生效日期", "绝缘下限", "关注倍数", "变化比例上限", "变化关注比例"]
const rulePlaceholders: Record<string, string> = {
  规则编号: '如 RULE-YJV22-2026',
  电缆型号: '与起止位置至少填一个',
  起止位置: '与电缆型号至少填一个',
  生效日期: 'YYYY-MM-DD',
  绝缘下限: '单位 MΩ，必填',
  关注倍数: '默认 1.5',
  变化比例上限: '百分比，超出即需处理',
  变化关注比例: '百分比，超出即关注',
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)
const showRules = ref(false)
const rules = ref<Row[]>([])
const ruleMessage = ref('')
const ruleForm = ref<Record<string, string>>({})

const stats = computed(() => [
  { label: '正常电缆', value: rows.value.filter((row) => row['判定结论'] === '正常').length },
  { label: '关注电缆', value: rows.value.filter((row) => row['判定结论'] === '关注').length },
  { label: '需处理电缆', value: rows.value.filter((row) => row['判定结论'] === '需处理').length },
])

function judgeClass(value: Row[string]) {
  if (value === '需处理') return 'judge-danger'
  if (value === '关注') return 'judge-watch'
  if (value === '正常') return 'judge-ok'
  return ''
}

function formatDetail(field: string, value: Row[string]) {
  if (value === null || value === undefined || value === '') return '—'
  if (field === '变化比例') return `${value}%`
  return value
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '电缆段登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电缆段详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function toggleRules() {
  showRules.value = !showRules.value
  if (showRules.value) {
    await loadRules()
  }
}

async function loadRules() {
  ruleMessage.value = ''
  try {
    rules.value = await fetchJson<Row[]>(`${ENDPOINT}/rules`)
  } catch (error) {
    ruleMessage.value = error instanceof Error ? error.message : '判定规则读取失败'
  }
}

async function submitRule() {
  ruleMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/rules`, {
      method: 'POST',
      body: JSON.stringify({ values: ruleForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '规则保存失败')
    }
    ruleForm.value = {}
    await loadRules()
    await reload()
  } catch (error) {
    ruleMessage.value = error instanceof Error ? error.message : '规则保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('电缆线路动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电缆线路操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('电缆段列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电缆线路列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.judge-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid transparent;
}
.judge-ok {
  color: #067647;
  background: #ecfdf3;
  border-color: #a6f4c5;
}
.judge-watch {
  color: #b54708;
  background: #fffaeb;
  border-color: #fedf89;
}
.judge-danger {
  color: #b42318;
  background: #fef3f2;
  border-color: #fecdca;
}
.rule-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.panel-title {
  margin: 0 0 4px;
  font-size: 14px;
}
.panel-desc {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 12px;
}
.rule-form {
  margin: 10px 0 0;
}
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.dialog {
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.dialog-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.dialog-head h3 {
  margin: 0;
  font-size: 15px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 12px;
  margin: 0 0 10px;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
  word-break: break-all;
}
</style>
