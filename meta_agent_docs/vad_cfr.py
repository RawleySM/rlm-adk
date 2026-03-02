# Copyright 2026
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Python implementation of the Volatility-Adaptive Discounted (VAD-)CFR algorithm.

Based on the paper: Discovering Multiagent Learning Algorithms with Large Language Models
"""

import collections
from typing import Dict, List

import attr
import numpy as np

from open_spiel.python import policy
import pyspiel


@attr.s
class _InfoStateNode(object):
    """An object wrapping values associated to an information state."""
    legal_actions: List[int] = attr.ib()
    index_in_tabular_policy: int = attr.ib()
    cumulative_regret: Dict[int, float] = attr.ib(
        factory=lambda: collections.defaultdict(float)
    )
    cumulative_policy: Dict[int, float] = attr.ib(
        factory=lambda: collections.defaultdict(float)
    )


class RegretAccumulator:
    """A class that updates cumulative regret using Adaptive Discounting with separate discounting for positive and negative regrets, and instantaneous regret boosting."""

    @staticmethod
    def _calculate_adaptive_params(
        iteration_number, cfr_regrets,
        base_alpha, base_beta,
        volatility_sensitivity, max_expected_instantaneous_regret,
        ewma_decay_factor, current_ewma_magnitude,
    ):
        t_plus_one = float(iteration_number + 1)
        instantaneous_regret_magnitude = max(
            (abs(r) for r in cfr_regrets.values()), default=0.0
        )

        if iteration_number == 0:
            projected_ewma = instantaneous_regret_magnitude
        else:
            projected_ewma = (
                ewma_decay_factor * instantaneous_regret_magnitude + (1.0 - ewma_decay_factor) * current_ewma_magnitude
            )

        if max_expected_instantaneous_regret > 0:
            normalized_volatility = min(1.0, projected_ewma / max_expected_instantaneous_regret)
        else:
            normalized_volatility = 0.0

        effective_alpha = max(0.1, base_alpha - volatility_sensitivity * normalized_volatility)
        effective_beta = base_beta - volatility_sensitivity * normalized_volatility
        effective_beta = min(effective_alpha, effective_beta)

        discount_factor_positive = (t_plus_one**effective_alpha) / (t_plus_one**effective_alpha + 1.0)
        discount_factor_negative = (t_plus_one**effective_beta) / (t_plus_one**effective_beta + 1.0)

        return projected_ewma, normalized_volatility, discount_factor_positive, discount_factor_negative

    def __init__(self, base_alpha=1.5, base_beta=-0.1, volatility_sensitivity=0.5, max_expected_instantaneous_regret=2.0, instantaneous_regret_boost_factor=1.1,
                 ewma_decay_factor=0.1, negative_regret_cap=-20.0):
        self._base_alpha = base_alpha
        self._base_beta = base_beta
        self._volatility_sensitivity = volatility_sensitivity
        self._max_expected_instantaneous_regret = max_expected_instantaneous_regret
        self._instantaneous_regret_boost_factor = instantaneous_regret_boost_factor
        self._ewma_decay_factor = ewma_decay_factor
        self._negative_regret_cap = negative_regret_cap
        self._ewma_instantaneous_regret_magnitude = 0.0

    def update_accumulate_regret(self, info_state_node, iteration_number, cfr_regrets):
        (
            self._ewma_instantaneous_regret_magnitude,
            _,
            discount_factor_positive,
            discount_factor_negative,
        ) = RegretAccumulator._calculate_adaptive_params(
            iteration_number=iteration_number,
            cfr_regrets=cfr_regrets,
            base_alpha=self._base_alpha,
            base_beta=self._base_beta,
            volatility_sensitivity=self._volatility_sensitivity,
            max_expected_instantaneous_regret=self._max_expected_instantaneous_regret,
            ewma_decay_factor=self._ewma_decay_factor,
            current_ewma_magnitude=self._ewma_instantaneous_regret_magnitude,
        )

        updated_cumulative_regret = {}
        for action in cfr_regrets:
            old_regret = info_state_node.cumulative_regret[action]
            instantaneous_regret_component = cfr_regrets[action]
            
            if instantaneous_regret_component > 0:
                instantaneous_regret_component *= self._instantaneous_regret_boost_factor

            if old_regret >= 0:
                discounted_old_regret = discount_factor_positive * old_regret
            else:
                discounted_old_regret = discount_factor_negative * old_regret

            new_regret = discounted_old_regret + instantaneous_regret_component
            new_regret = max(self._negative_regret_cap, new_regret)
            updated_cumulative_regret[action] = new_regret

        return updated_cumulative_regret


class PolicyFromRegretAccumulator:
    def __init__(self, initial_optimism_factor=1.0,
                 optimism_decay_factor=100.0, positive_policy_exponent=1.5,
                 base_alpha=1.5, base_beta=-0.1,
                 volatility_sensitivity=0.5, max_expected_instantaneous_regret=2.0,
                 instantaneous_regret_boost_factor=1.1, ewma_decay_factor=0.1):
        self._initial_optimism_factor = initial_optimism_factor
        self._optimism_decay_factor = optimism_decay_factor
        self._positive_policy_exponent = positive_policy_exponent
        self._base_alpha = base_alpha
        self._base_beta = base_beta
        self._volatility_sensitivity = volatility_sensitivity
        self._max_expected_instantaneous_regret = max_expected_instantaneous_regret
        self._instantaneous_regret_boost_factor = instantaneous_regret_boost_factor
        self._ewma_decay_factor = ewma_decay_factor
        self._ewma_instantaneous_regret_magnitude = 0.0

    def get_updated_current_policy(self, info_state_node, iteration_number, cfr_regrets, previous_policy):
        (
            self._ewma_instantaneous_regret_magnitude,
            normalized_volatility,
            discount_factor_positive,
            discount_factor_negative,
        ) = RegretAccumulator._calculate_adaptive_params(
            iteration_number=iteration_number,
            cfr_regrets=cfr_regrets,
            base_alpha=self._base_alpha,
            base_beta=self._base_beta,
            volatility_sensitivity=self._volatility_sensitivity,
            max_expected_instantaneous_regret=self._max_expected_instantaneous_regret,
            ewma_decay_factor=self._ewma_decay_factor,
            current_ewma_magnitude=self._ewma_instantaneous_regret_magnitude,
        )

        base_optimism = self._initial_optimism_factor / (1.0 + float(iteration_number) / self._optimism_decay_factor)
        optimism_dampening_factor = max(0.0, 1.0 - self._volatility_sensitivity * normalized_volatility)
        optimism_strength = base_optimism * optimism_dampening_factor

        action_to_projected_regret = {}
        for action in info_state_node.legal_actions:
            old_cumulative_regret = info_state_node.cumulative_regret.get(action, 0.0)
            instantaneous_regret = cfr_regrets.get(action, 0.0)
            
            instantaneous_regret_component = instantaneous_regret
            if instantaneous_regret_component > 0:
                instantaneous_regret_component *= self._instantaneous_regret_boost_factor

            if old_cumulative_regret >= 0:
                discounted_old_regret = discount_factor_positive * old_cumulative_regret
            else:
                discounted_old_regret = discount_factor_negative * old_cumulative_regret

            projected_regret = discounted_old_regret + optimism_strength * instantaneous_regret_component
            action_to_projected_regret[action] = projected_regret

        positive_scaled_projected_regrets = {
            action: (max(0.0, regret) ** self._positive_policy_exponent)
            for action, regret in action_to_projected_regret.items()
        }

        sum_positive_scaled_projected_regrets = sum(positive_scaled_projected_regrets.values())

        info_state_policy = {}
        if sum_positive_scaled_projected_regrets > 0:
            for action, scaled_regret in positive_scaled_projected_regrets.items():
                info_state_policy[action] = scaled_regret / sum_positive_scaled_projected_regrets
        else:
            num_legal_actions = len(info_state_node.legal_actions)
            for action in info_state_node.legal_actions:
                info_state_policy[action] = 1.0 / num_legal_actions

        return info_state_policy


class PolicyAccumulator:
    def __init__(self, base_gamma=2.0, gamma_max=4.0, gamma_volatility_sensitivity=1.5, warmup_iterations=500,
                 stability_exponent=1.5, max_expected_instantaneous_regret=2.0, regret_magnitude_weighting_exponent=0.5):
        self._base_gamma = base_gamma
        self._gamma_max = gamma_max
        self._gamma_volatility_sensitivity = gamma_volatility_sensitivity
        self._warmup_iterations = warmup_iterations
        self._stability_exponent = stability_exponent
        self._max_expected_instantaneous_regret = max_expected_instantaneous_regret
        self._regret_magnitude_weighting_exponent = regret_magnitude_weighting_exponent

    def update_accumulate_policy(
        self,
        info_state_node, iteration_number,
        info_state_policy, cfr_regrets,
        reach_prob, counterfactual_reach_prob,
    ):
        if iteration_number < self._warmup_iterations:
            return info_state_node.cumulative_policy

        instantaneous_regret_magnitude = max(
            (abs(r) for r in cfr_regrets.values()), default=0.0
        )

        if self._max_expected_instantaneous_regret > 0:
            normalized_volatility = min(1.0, instantaneous_regret_magnitude / self._max_expected_instantaneous_regret)
        else:
            normalized_volatility = 0.0

        effective_gamma = self._base_gamma + self._gamma_volatility_sensitivity * normalized_volatility
        effective_gamma = min(self._gamma_max, effective_gamma)

        temporal_weight = (float(iteration_number) + 1.0) ** effective_gamma

        regret_stability_factor = 1.0 / (1.0 + instantaneous_regret_magnitude**self._stability_exponent)

        regret_magnitude_factor = (
            1.0 + (instantaneous_regret_magnitude / self._max_expected_instantaneous_regret)
        ) ** self._regret_magnitude_weighting_exponent
        regret_magnitude_factor = max(0.1, regret_magnitude_factor)

        weight = temporal_weight * regret_stability_factor * regret_magnitude_factor

        return {
            action: (
                info_state_node.cumulative_policy[action] + weight * reach_prob * info_state_policy[action]
            ) for action in info_state_policy
        }


class VADCFRSolver(object):
    """Implements the Volatility-Adaptive Discounted Counterfactual Regret Minimization (VAD-CFR) algorithm."""

    def __init__(self, game: pyspiel.Game):
        assert game.get_type().dynamics == pyspiel.GameType.Dynamics.SEQUENTIAL, (
            "CFR requires sequential games. If you're trying to run it " +
            "on a simultaneous (or normal-form) game, please first transform it " +
            "using turn_based_simultaneous_game.")

        self._game = game
        self._num_players = game.num_players()
        self._root_node = self._game.new_initial_state()

        self._current_policy = policy.TabularPolicy(game)
        self._average_policy = self._current_policy.__copy__()

        self._info_state_nodes: Dict[str, _InfoStateNode] = {}
        self._initialize_info_state_nodes(self._root_node)

        self._iteration = 0
        
        self._regret_accumulator = RegretAccumulator()
        self._policy_from_regret_accumulator = PolicyFromRegretAccumulator()
        self._policy_accumulator = PolicyAccumulator()

    def _initialize_info_state_nodes(self, state: pyspiel.State):
        if state.is_terminal():
            return

        if state.is_chance_node():
            for action, unused_action_prob in state.chance_outcomes():
                self._initialize_info_state_nodes(state.child(action))
            return

        current_player = state.current_player()
        info_state = state.information_state_string(current_player)

        info_state_node = self._info_state_nodes.get(info_state)
        if info_state_node is None:
            legal_actions = state.legal_actions(current_player)
            info_state_node = _InfoStateNode(
                legal_actions=legal_actions,
                index_in_tabular_policy=self._current_policy.state_lookup[info_state])
            self._info_state_nodes[info_state] = info_state_node

        for action in info_state_node.legal_actions:
            self._initialize_info_state_nodes(state.child(action))

    def _update_average_policy(self):
        for info_state, info_state_node in self._info_state_nodes.items():
            info_state_policies_sum = info_state_node.cumulative_policy
            state_policy = self._average_policy.policy_for_key(info_state)
            probabilities_sum = sum(info_state_policies_sum.values())
            if probabilities_sum == 0:
                num_actions = len(info_state_node.legal_actions)
                for action in info_state_node.legal_actions:
                    state_policy[action] = 1.0 / num_actions
            else:
                for action, action_prob_sum in info_state_policies_sum.items():
                    state_policy[action] = action_prob_sum / probabilities_sum

    def current_policy(self) -> policy.TabularPolicy:
        return self._current_policy

    def average_policy(self) -> policy.TabularPolicy:
        self._update_average_policy()
        return self._average_policy

    def evaluate_and_update_policy(self):
        """Performs a single step of policy evaluation and policy improvement."""
        # VAD-CFR typically uses alternating updates.
        for player in range(self._game.num_players()):
            self._compute_counterfactual_regret_for_player(
                self._root_node,
                reach_probabilities=np.ones(self._game.num_players() + 1),
                player=player)
        self._iteration += 1

    def _compute_counterfactual_regret_for_player(
        self,
        state: pyspiel.State,
        reach_probabilities: np.ndarray,
        player: int,
    ):
        if state.is_terminal():
            return np.asarray(state.returns())

        if state.is_chance_node():
            state_value = 0.0
            for action, action_prob in state.chance_outcomes():
                assert action_prob > 0
                new_state = state.child(action)
                new_reach_probabilities = reach_probabilities.copy()
                new_reach_probabilities[-1] *= action_prob
                state_value += action_prob * self._compute_counterfactual_regret_for_player(
                    new_state, new_reach_probabilities, player)
            return state_value

        current_player = state.current_player()
        info_state = state.information_state_string(current_player)

        if all(reach_probabilities[:-1] == 0):
            return np.zeros(self._num_players)

        state_value = np.zeros(self._num_players)
        children_utilities = {}
        
        info_state_node = self._info_state_nodes[info_state]
        prob_vec = self._current_policy.action_probability_array[info_state_node.index_in_tabular_policy]
        info_state_policy = {action: prob_vec[action] for action in info_state_node.legal_actions}

        for action in state.legal_actions():
            action_prob = info_state_policy.get(action, 0.)
            new_state = state.child(action)
            new_reach_probabilities = reach_probabilities.copy()
            new_reach_probabilities[current_player] *= action_prob
            child_utility = self._compute_counterfactual_regret_for_player(
                new_state,
                reach_probabilities=new_reach_probabilities,
                player=player)

            state_value += action_prob * child_utility
            children_utilities[action] = child_utility

        if current_player != player:
            return state_value

        reach_prob = reach_probabilities[current_player]
        counterfactual_reach_prob = (
            np.prod(reach_probabilities[:current_player]) *
            np.prod(reach_probabilities[current_player + 1:]))
        state_value_for_player = state_value[current_player]

        cfr_regrets = {}
        for action, action_prob in info_state_policy.items():
            cfr_regret = counterfactual_reach_prob * (
                children_utilities[action][current_player] - state_value_for_player)
            cfr_regrets[action] = cfr_regret

        # 1. Update Accumulate Regret
        updated_cumulative_regret = self._regret_accumulator.update_accumulate_regret(
            info_state_node, self._iteration, cfr_regrets)
        for act, reg in updated_cumulative_regret.items():
            info_state_node.cumulative_regret[act] = reg
            
        # 2. Update Accumulate Policy
        updated_cumulative_policy = self._policy_accumulator.update_accumulate_policy(
            info_state_node, self._iteration, info_state_policy, cfr_regrets,
            reach_prob, counterfactual_reach_prob)
        for act, p in updated_cumulative_policy.items():
            info_state_node.cumulative_policy[act] = p

        # 3. Get Updated Current Policy
        updated_current_policy = self._policy_from_regret_accumulator.get_updated_current_policy(
            info_state_node, self._iteration, cfr_regrets, info_state_policy)
            
        state_policy_array = self._current_policy.policy_for_key(info_state)
        for act, prob in updated_current_policy.items():
            state_policy_array[act] = prob

        return state_value
