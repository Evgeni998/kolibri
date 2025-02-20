<template>

  <CoreBase
    :immersivePage="false"
    :authorized="userIsAuthorized"
    authorizedRole="adminOrCoach"
    :showSubNav="true"
  >

    <template #sub-nav>
      <TopNavbar />
    </template>

    <KPageContainer>
      <ReportsHeader :title="$isPrint ? $tr('printLabel', { className }) : null" />
      <ReportsControls @export="exportCSV" />
      <CoreTable :emptyMessage="coachString('learnerListEmptyState')">
        <template #headers>
          <th>{{ coachString('nameLabel') }}</th>
          <th>{{ coachString('groupsLabel') }}</th>
          <th>{{ coachString('avgQuizScoreLabel') }}</th>
          <th>{{ coachString('exercisesCompletedLabel') }}</th>
          <th>{{ coachString('resourcesViewedLabel') }}</th>
          <th>{{ coachString('lastActivityLabel') }}</th>
        </template>
        <template #tbody>
          <transition-group tag="tbody" name="list">
            <tr v-for="tableRow in table" :key="tableRow.id">
              <td>
                <KRouterLink
                  :text="tableRow.name"
                  :to="classRoute('ReportsLearnerReportPage', { learnerId: tableRow.id })"
                  icon="person"
                />
              </td>
              <td><TruncatedItemList :items="tableRow.groups" /></td>
              <td><Score :value="tableRow.avgScore" /></td>
              <td>{{ $formatNumber(tableRow.exercises) }}</td>
              <td>{{ $formatNumber(tableRow.resources) }}</td>
              <td><ElapsedTime :date="tableRow.lastActivity" /></td>
            </tr>
          </transition-group>
        </template>
      </CoreTable>
    </KPageContainer>
  </CoreBase>

</template>


<script>

  import sortBy from 'lodash/sortBy';
  import ElapsedTime from 'kolibri.coreVue.components.ElapsedTime';
  import commonCoach from '../common';
  import CSVExporter from '../../csv/exporter';
  import * as csvFields from '../../csv/fields';
  import ReportsControls from './ReportsControls';
  import ReportsHeader from './ReportsHeader';

  export default {
    name: 'ReportsLearnerListPage',
    components: {
      ReportsControls,
      ReportsHeader,
      ElapsedTime,
    },
    mixins: [commonCoach],
    computed: {
      table() {
        const sorted = sortBy(this.learners, ['name']);
        return sorted.map(learner => {
          const groupNames = this.getGroupNames(
            this._.map(
              this.groups.filter(group => group.member_ids.includes(learner.id)),
              'id'
            )
          );
          const examStatuses = this.examStatuses.filter(status => learner.id === status.learner_id);
          const contentStatuses = this.contentStatuses.filter(
            status => learner.id === status.learner_id
          );
          const augmentedObj = {
            groups: groupNames,
            avgScore: this.avgScore(examStatuses),
            lessons: undefined,
            exercises: this.exercisesCompleted(contentStatuses),
            resources: this.resourcesViewed(contentStatuses),
            lastActivity: this.lastActivity(examStatuses, contentStatuses),
          };
          Object.assign(augmentedObj, learner);
          return augmentedObj;
        });
      },
    },
    methods: {
      avgScore(examStatuses) {
        const statuses = examStatuses.filter(status => status.status === this.STATUSES.completed);
        if (!statuses.length) {
          return null;
        }
        return this._.meanBy(statuses, 'score');
      },
      lastActivity(examStatuses, contentStatuses) {
        const statuses = [
          ...examStatuses,
          ...contentStatuses.filter(status => status.status !== this.STATUSES.notStarted),
        ];

        return statuses.length ? this.maxLastActivity(statuses) : null;
      },
      exercisesCompleted(contentStatuses) {
        const statuses = contentStatuses.filter(
          status =>
            this.contentIdIsForExercise(status.content_id) &&
            status.status === this.STATUSES.completed
        );
        return statuses.length;
      },
      resourcesViewed(contentStatuses) {
        const statuses = contentStatuses.filter(
          status =>
            !this.contentIdIsForExercise(status.content_id) &&
            status.status !== this.STATUSES.notStarted
        );
        return statuses.length;
      },
      exportCSV() {
        const columns = [
          ...csvFields.name(),
          ...csvFields.list('groups', 'groupsLabel'),
          ...csvFields.avgScore(true),
          {
            name: this.coachString('exercisesCompletedLabel'),
            key: 'exercises',
          },
          {
            name: this.coachString('resourcesViewedLabel'),
            key: 'resources',
          },
          ...csvFields.lastActivity(),
        ];

        const fileName = this.$tr('printLabel', { className: this.className });
        new CSVExporter(columns, fileName).export(this.table);
      },
    },
    $trs: {
      printLabel: {
        message: '{className} Learners',
        context:
          "Title that displays on a printed copy of the 'Reports' > 'Learners' page. This shows if the user uses the 'Print' option by clicking on the printer icon.",
      },
    },
  };

</script>


<style lang="scss" scoped>

  @import '../common/print-table';

</style>
