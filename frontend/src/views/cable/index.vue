<template>
  <section class="page" data-module="cable">
    <header class="page-head">
      <div>
        <h2>电缆线路管理</h2>
        <p class="page-desc">维护电缆段，围绕电缆编号、电缆型号、起止位置、敷设方式做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电缆段</button>
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
            <span v-if="column === '绝缘判定'" class="judge-tag" :class="judgeClass(row[column])">
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

    <section v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>电缆段详情 · {{ detail['电缆编号'] }}</h3>
        <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
      </header>
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>
            <span v-if="field === '绝缘判定'" class="judge-tag" :class="judgeClass(detail[field])">
              {{ detail[field] ?? '—' }}
            </span>
            <template v-else>{{ detail[field] ?? '—' }}</template>
          </dd>
        </template>
      </dl>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条电缆线路记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/cable'
const columns = ["电缆编号", "电缆型号", "起止位置", "敷设方式", "绝缘电阻", "上次测值", "测试日期", "电缆状态", "绝缘判定", "判定结论"]
const actions = ["测试绝缘", "标记隐患", "安排修复"]
const detailFields = columns

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)

const stats = computed(() => [
  { label: '判定正常', value: rows.value.filter((row) => row['绝缘判定'] === '正常').length },
  { label: '判定关注', value: rows.value.filter((row) => row['绝缘判定'] === '关注').length },
  { label: '判定需处理', value: rows.value.filter((row) => row['绝缘判定'] === '需处理').length },
])

function judgeClass(value: string | number | null | undefined) {
  if (value === '需处理') return 'danger'
  if (value === '关注') return 'warn'
  return 'ok'
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

function closeDetail() {
  detail.value = null
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('电缆段详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电缆段详情读取失败'
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
