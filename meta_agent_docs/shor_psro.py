import numpy as np

def _smoothed_best_pure_strategy(payoff_vec, temperature=1.0):
    """Computes a smoothed distribution biased towards the best pure strategy.
    The softmax function ensures that strategies with higher payoffs are
    given higher probability, with 'temperature' controlling the sharpness
    of the distribution. A lower temperature makes the distribution more
    concentrated on the best strategy, while a higher temperature leads to
    a more uniform distribution.
    """
    # Subtract max payoff for numerical stability (standard softmax trick)
    stable_payoffs = payoff_vec - np.max(payoff_vec)
    exp_payoffs = np.exp(stable_payoffs / temperature)
    sum_exp_payoffs = np.sum(exp_payoffs)
    if sum_exp_payoffs > 1e-12: # Avoid division by zero
        return exp_payoffs / sum_exp_payoffs
    else:
        # Fallback to uniform distribution if all exponentiated payoffs are
        # effectively zero (e.g., due to very low temperature and negative payoffs,
        # or all payoffs being identical after stabilization).
        return np.ones_like(payoff_vec) / len(payoff_vec)

def _hybrid_orm_solver(meta_games, iterations, blending_factor=0.0,
                      temperature=0.1, momentum_beta=0.0,
                      gain_normalization=True, diversity_bonus_coeff=0.0,
                      return_average_strategy=True):
    """Computes meta-strategies using Optimistic Regret Matching+ enhanced with
    optimistic updates, gain normalization, and a diversity bonus, then blended
    with a smoothed best pure strategy.

    This solver combines the stability and convergence properties of Optimistic
    Regret Matching+ (ORM+) with an explicit pull towards highly rewarding
    pure strategies, smoothed by a temperature-controlled softmax. This hybrid
    approach aims to leverage ORM+'s ability to find mixed equilibria while
    also quickly identifying and exploring strong pure-strategy modes in the
    meta-game, thereby potentially accelerating the discovery of low-exploitable
    policies in PSRO. The blending factor controls the trade-off between these
    two dynamics.

    Args:
      meta_games: A list of n-dimensional numpy arrays, one per player.
      iterations: Number of internal solver iterations.
      blending_factor: Weight (0 to 1) for blending ORM+ output with the
        smoothed best pure strategy. A factor of 0 means pure ORM+; 1 means
        pure smoothed best pure strategy.
      temperature: Temperature for softmax smoothing when calculating the
        smoothed best pure strategy. Lower values make the smoothing sharper.
      momentum_beta: Momentum parameter for optimistic updates to payoff gains.
      gain_normalization: If True, normalizes payoff gains to make learning rate
        more robust across games.
      diversity_bonus_coeff: Coefficient for diversity bonus, encouraging
        exploration of less-chosen policies.
      return_average_strategy: If True, returns time-averaged strategies.
        If False, returns last-iterate strategies.

    Returns:
      A list of mixed-strategies, one for each player, as numpy arrays.
    """
    num_players = len(meta_games)
    num_strats = [m.shape[i] for i, m in enumerate(meta_games)]

    if any(n_s == 0 for n_s in num_strats):
        return [np.array([]).tolist() for _ in range(num_players)]

    strategies = [np.ones(s, dtype=float) / s for s in num_strats]
    cum_regrets = [np.zeros(s, dtype=float) for s in num_strats]
    avg_strategies = [np.zeros(s, dtype=float) for s in num_strats]
    prev_centered_payoff_gains = [np.zeros(s, dtype=float) for s in num_strats]

    for t in range(iterations):
        current_centered_payoff_gains = [np.zeros(s, dtype=float) for s in num_strats]
        orm_strategies_this_iter = [np.zeros(s, dtype=float) for s in num_strats]

        for p in range(num_players):
            payoff_vec = meta_games[p]
            for other_p in reversed(range(num_players)):
                if other_p != p:
                    payoff_vec = np.tensordot(payoff_vec, strategies[other_p], axes=([other_p], [0]))

            centered_payoff_gains = payoff_vec - np.mean(payoff_vec)
            current_centered_payoff_gains[p] = centered_payoff_gains
            optimistic_payoff_gains = (1 + momentum_beta) * centered_payoff_gains - \
                                      momentum_beta * prev_centered_payoff_gains[p]

            diversity_bonus = diversity_bonus_coeff * (1.0 - strategies[p])
            gains_for_regret_update = optimistic_payoff_gains + diversity_bonus

            if gain_normalization:
                max_abs_gain = np.max(np.abs(gains_for_regret_update))
                if max_abs_gain > 1e-8:
                    gains_for_regret_update /= max_abs_gain

            cum_regrets[p] += gains_for_regret_update
            cum_regrets[p] = np.maximum(0, cum_regrets[p])

            sum_pos_regret = cum_regrets[p].sum()
            if sum_pos_regret > 1e-12:
                orm_strategies_this_iter[p] = cum_regrets[p] / sum_pos_regret
            else:
                orm_strategies_this_iter[p] = np.ones(num_strats[p]) / num_strats[p]

            smoothed_best_pure = _smoothed_best_pure_strategy(payoff_vec, temperature)

            strategies[p] = (1 - blending_factor) * orm_strategies_this_iter[p] + \
                             blending_factor * smoothed_best_pure
            
            prev_centered_payoff_gains[p] = current_centered_payoff_gains[p]

        if return_average_strategy:
            # Accumulate blended strategy only if average is requested
            for p in range(num_players):
                avg_strategies[p] += strategies[p]

    if return_average_strategy:
        final_strategies = []
        for p in range(num_players):
            sum_avg_strat = np.sum(avg_strategies[p])
            if sum_avg_strat > 0:
                final_strategies.append(avg_strategies[p] / sum_avg_strat)
            else:
                final_strategies.append(np.ones(num_strats[p]) / num_strats[p])
        return final_strategies
    else:
        # If not returning average, return the last-iterate strategies
        return strategies

class TrainMetaStrategySolver:
    """A hybrid meta-solver for training that blends ORM+ with smoothed best pure strategies.
    This solver aims to accelerate convergence to low-exploitable strategies by dynamically
    balancing regret-minimization with a pull towards high-performing (but smoothed)
    pure strategies. Optimistic updates, gain normalization, and a diversity bonus are
    incorporated for improved learning dynamics. The blending factor, temperature, and
    diversity bonus are annealed over the outer PSRO iterations.
    """
    def __init__(self, base_solver_iterations=1000,
                 iterations_per_policy_scale=20,
                 max_solver_iterations=5000,
                 initial_blending_factor=0.3,
                 final_blending_factor=0.05,
                 initial_temperature=0.5,
                 final_temperature=0.01,
                 momentum_beta=0.5,
                 gain_normalization=True,
                 initial_diversity_bonus_coeff=0.05,
                 final_diversity_bonus_coeff=0.001,
                 max_psro_iterations_for_annealing=75):
        """Initializes hybrid ORM solver parameters for training."""
        self._base_solver_iterations = base_solver_iterations
        self._iterations_per_policy_scale = iterations_per_policy_scale
        self._max_solver_iterations = max_solver_iterations
        self._initial_blending_factor = initial_blending_factor
        self._final_blending_factor = final_blending_factor
        self._initial_temperature = initial_temperature
        self._final_temperature = final_temperature
        self._momentum_beta = momentum_beta
        self._gain_normalization = gain_normalization
        self._initial_diversity_bonus_coeff = initial_diversity_bonus_coeff
        self._final_diversity_bonus_coeff = final_diversity_bonus_coeff
        self._max_psro_iterations_for_annealing = max_psro_iterations_for_annealing
        self._current_psro_iteration = 0

    def get_meta_strategy(self, game, policy_sets, meta_games):
        """Returns blended meta strategies for training."""
        del game, policy_sets # Unused
        self._current_psro_iteration += 1
        current_psro_iter = self._current_psro_iteration

        # Adaptive solver iterations: scale with current population size
        num_current_policies_p0 = len(meta_games[0]) # Assuming symmetric populations
        solver_iterations = int(self._base_solver_iterations +
                               self._iterations_per_policy_scale * (num_current_policies_p0 - 1))
        solver_iterations = np.clip(solver_iterations, self._base_solver_iterations,
                                   self._max_solver_iterations)

        annealing_progress = min(1.0, current_psro_iter / self._max_psro_iterations_for_annealing)

        blending_factor = (self._initial_blending_factor * (1.0 - annealing_progress) +
                          self._final_blending_factor * annealing_progress)
        temperature = (self._initial_temperature * (1.0 - annealing_progress) +
                      self._final_temperature * annealing_progress)
        diversity_bonus_coeff = (self._initial_diversity_bonus_coeff * (1.0 - annealing_progress) +
                                self._final_diversity_bonus_coeff * annealing_progress)

        blending_factor = np.clip(blending_factor, self._final_blending_factor,
                                 self._initial_blending_factor)
        temperature = np.clip(temperature, self._final_temperature, self._initial_temperature)
        diversity_bonus_coeff = np.clip(diversity_bonus_coeff, self._final_diversity_bonus_coeff,
                                       self._initial_diversity_bonus_coeff)

        strategies = _hybrid_orm_solver(
            meta_games,
            iterations=solver_iterations,
            blending_factor=blending_factor,
            temperature=temperature,
            momentum_beta=self._momentum_beta,
            gain_normalization=self._gain_normalization,
            diversity_bonus_coeff=diversity_bonus_coeff,
            return_average_strategy=True
        )

        return [s.tolist() for s in strategies]

class EvalMetaStrategySolver:
    """Returns meta strategies for evaluation in PSRO.
    This solver uses a hybrid approach, blending Optimistic Regret Matching+ with a
    smoothed best pure strategy, tailored for robust and accurate exploitability
    measurement. The parameters are set to emphasize exploitation for evaluation
    purposes, including optimistic updates and gain normalization for stability,
    while keeping diversity bonus minimal. Crucially, it returns the last-iterate
    strategy for a reactive estimate of exploitability.
    """
    def __init__(self, base_solver_iterations=8000,
                 iterations_per_policy_scale=50,
                 max_solver_iterations=15000,
                 blending_factor=0.01,
                 temperature=0.001,
                 momentum_beta=0.2,
                 gain_normalization=True,
                 diversity_bonus_coeff=0.0):
        """Initializes hybrid ORM solver parameters for evaluation meta-strategies."""
        self._base_solver_iterations = base_solver_iterations
        self._iterations_per_policy_scale = iterations_per_policy_scale
        self._max_solver_iterations = max_solver_iterations
        self._blending_factor = blending_factor
        self._temperature = temperature
        self._momentum_beta = momentum_beta
        self._gain_normalization = gain_normalization
        self._diversity_bonus_coeff = diversity_bonus_coeff

    def get_meta_strategy(self, game, policy_sets, meta_games):
        """Returns blended meta strategies for evaluation in policy-space response oracles."""
        del game, policy_sets # Unused
        num_current_policies_p0 = len(meta_games[0]) # Assuming symmetric populations
        solver_iterations = int(self._base_solver_iterations +
                               self._iterations_per_policy_scale * (num_current_policies_p0 - 1))
        solver_iterations = np.clip(solver_iterations, self._base_solver_iterations,
                                   self._max_solver_iterations)

        strategies = _hybrid_orm_solver(
            meta_games,
            iterations=solver_iterations,
            blending_factor=self._blending_factor,
            temperature=self._temperature,
            momentum_beta=self._momentum_beta,
            gain_normalization=self._gain_normalization,
            diversity_bonus_coeff=self._diversity_bonus_coeff,
            return_average_strategy=False
        )

        return [s.tolist() for s in strategies]
