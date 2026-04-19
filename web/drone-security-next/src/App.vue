<template>
  <div class="app-shell">
    <AppHeader :runtime="runtime" :line-state="lineState" />

    <main class="app-grid">
      <aside class="panel">
        <AttackPanel
          :attack-options="attackOptions"
          :selected-attack-id="selectedAttackId"
          :selected-target-id="selectedTargetId"
          :selected-attack="selectedAttack"
          :defense-enabled="defenseEnabled"
          :is-busy="isBusy"
          :status-message="statusMessage"
          :attack-result="attackResult"
          :can-defend="Boolean(currentAttackId)"
          @select-attack="setSelectedAttack"
          @select-target="setSelectedTarget"
          @toggle-defense="setDefenseEnabled"
          @launch="launchAttack"
          @defend-now="defendNow"
          @scenario="activateScenario"
        />
      </aside>

      <section class="panel panel-center">
        <TopologyPanel
          :attack-event="attackEvent"
          :defend-event="defendEvent"
          :reset-event="resetEvent"
          :telemetry="telemetry"
          :history="history"
          :line-state="lineState"
          :current-attack-id="currentAttackId"
          @restore="restoreFromExplosion"
        />
      </section>

      <aside class="panel">
        <EvaluationPanel
          :phase="phase"
          :attack-event="attackEvent"
          :defend-event="defendEvent"
          :reset-event="resetEvent"
          :telemetry="telemetry"
          :current-attack-id="currentAttackId"
          :selected-attack-id="selectedAttackId"
          :selected-target-id="currentAttackId ? currentTargetId : selectedTargetId"
        />
      </aside>
    </main>
  </div>
</template>

<script setup>
import AppHeader from './components/layout/AppHeader.vue'
import AttackPanel from './components/panels/AttackPanel.vue'
import EvaluationPanel from './components/panels/EvaluationPanel.vue'
import TopologyPanel from './components/panels/TopologyPanel.vue'
import { useControlTower } from './composables/useControlTower'

const {
  attackOptions,
  selectedAttack,
  selectedAttackId,
  selectedTargetId,
  defenseEnabled,
  isBusy,
  phase,
  statusMessage,
  attackResult,
  telemetry,
  runtime,
  lineState,
  history,
  currentAttackId,
  currentTargetId,
  attackEvent,
  defendEvent,
  resetEvent,
  setSelectedAttack,
  setSelectedTarget,
  setDefenseEnabled,
  launchAttack,
  defendNow,
  activateScenario,
  restoreFromExplosion,
} = useControlTower()
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  height: 100%;
  padding: 10px;
}

.app-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr) 360px;
  gap: 10px;
  flex: 1;
  min-height: 0;
}

.panel {
  min-height: 0;
  padding: 12px;
  border: 1px solid var(--border-soft);
  border-radius: 20px;
  background: linear-gradient(180deg, var(--bg-panel) 0%, var(--bg-panel-strong) 100%);
  box-shadow: var(--shadow-panel);
  overflow: auto;
}

.panel-center {
  display: flex;
}

@media (max-width: 1480px) {
  .app-grid {
    grid-template-columns: 320px minmax(0, 1fr) 320px;
  }
}

@media (max-width: 1220px) {
  .app-grid {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .panel {
    min-height: 360px;
  }
}
</style>
