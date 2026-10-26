/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
import { createSlice } from '@reduxjs/toolkit';

const { reducer, actions } = createSlice({
  name: 'errors',
  initialState: {
    errors: [],
  },
  reducers: {
    push(state, action) {
      state.errors.push(action.payload);
    },
    pop(state) {
      if (state.errors.length) {
        state.errors.shift();
      }
    },
  },
});

export { actions as errorsActions };
export { reducer as errorsReducer };
