/**
 * AppPagination - 分页组件
 * 支持上一页/下一页、页码数字、省略号逻辑
 * Props: currentPage, totalPages
 * Emits: @page-change
 */
const AppPagination = {
  name: 'AppPagination',
  template: `
    <div class="flex items-center justify-center space-x-1 mt-6" v-if="totalPages > 0">
      <!-- 上一页 -->
      <button
        @click="goToPage(currentPage - 1)"
        :disabled="currentPage <= 1"
        class="px-3 py-2 text-sm rounded-lg border transition-colors"
        :class="currentPage <= 1
          ? 'border-gray-200 text-gray-300 cursor-not-allowed bg-gray-50'
          : 'border-gray-300 text-gray-600 hover:bg-gray-100 hover:text-gray-800'">
        <i class="fas fa-chevron-left mr-1"></i>上一页
      </button>

      <!-- 页码按钮 -->
      <template v-for="(page, index) in pageNumbers" :key="index">
        <!-- 省略号 -->
        <span v-if="page === '...'" class="px-3 py-2 text-sm text-gray-400 select-none">...</span>
        <!-- 页码 -->
        <button
          v-else
          @click="goToPage(page)"
          class="px-3 py-2 text-sm rounded-lg border transition-colors min-w-[36px]"
          :class="page === currentPage
            ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700'
            : 'border-gray-300 text-gray-600 hover:bg-gray-100'">
          {{ page }}
        </button>
      </template>

      <!-- 下一页 -->
      <button
        @click="goToPage(currentPage + 1)"
        :disabled="currentPage >= totalPages"
        class="px-3 py-2 text-sm rounded-lg border transition-colors"
        :class="currentPage >= totalPages
          ? 'border-gray-200 text-gray-300 cursor-not-allowed bg-gray-50'
          : 'border-gray-300 text-gray-600 hover:bg-gray-100 hover:text-gray-800'">
        下一页<i class="fas fa-chevron-right ml-1"></i>
      </button>
    </div>
  `,
  props: {
    currentPage: {
      type: Number,
      required: true,
      validator: (value) => value >= 1
    },
    totalPages: {
      type: Number,
      required: true,
      validator: (value) => value >= 0
    }
  },
  setup(props, { emit }) {
    const { computed } = Vue;

    /**
     * 生成带省略号的页码数组
     * 规则:
     * - 始终显示第 1 页
     * - 始终显示最后 1 页
     * - 当前页前后各显示 2 页
     * - 缺口处用 '...' 填充
     */
    const pageNumbers = computed(() => {
      const pages = [];
      const total = props.totalPages;

      if (total <= 7) {
        // 页数少时全部显示
        for (let i = 1; i <= total; i++) {
          pages.push(i);
        }
        return pages;
      }

      // 始终显示第一页
      pages.push(1);

      let rangeStart = Math.max(2, props.currentPage - 2);
      let rangeEnd = Math.min(total - 1, props.currentPage + 2);

      // 调整范围，保证至少显示 5 个可点击的页码（不含首尾）
      if (rangeEnd - rangeStart < 3) {
        if (props.currentPage < total / 2) {
          rangeEnd = Math.min(rangeStart + 3, total - 1);
        } else {
          rangeStart = Math.max(rangeEnd - 3, 2);
        }
      }

      // 第一页后有缺口
      if (rangeStart > 2) {
        pages.push('...');
      }

      // 中间页码
      for (let i = rangeStart; i <= rangeEnd; i++) {
        pages.push(i);
      }

      // 最后页前有缺口
      if (rangeEnd < total - 1) {
        pages.push('...');
      }

      // 始终显示最后一页
      if (total > 1) {
        pages.push(total);
      }

      return pages;
    });

    const goToPage = (page) => {
      if (page >= 1 && page <= props.totalPages && page !== props.currentPage) {
        emit('page-change', page);
      }
    };

    return {
      pageNumbers,
      goToPage
    };
  }
};
