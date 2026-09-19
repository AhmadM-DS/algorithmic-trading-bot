"""
supply_demand.py
Implements the Supply and Demand strategy, built on the limit order book
model from Obizhaeva & Wang (2005), "Optimal Trading Strategy and
Supply/Demand Dynamics" (NBER Working Paper 11444).
"""

#Standard Library
import math

#Third party libraries
import numpy as np
import pandas as pd

#Local imports
from strategies.base_strategy import Strategy

"""
Strategy Workflow
Obizhaeva & Wang split a trade's price impact into a permanent shift of the
steady-state price and a transient deviation from it, D_t, which decays at
rate rho (the book's "resilience") as new limit orders arrive to refill the
book (eqs. 6-10). The paper uses this to schedule a large order; this
strategy takes the other side of that trade. When heavy selling pushes
price below its steady state, the model expects new buy orders to lift it
back, so the strategy buys the displacement and sells once the model says
it has decayed. The permanent part of impact moves the steady state itself,
so there is nothing in it to trade back.

Daily bars carry no order book, so the model is fitted to proxies:
    -Signed flow: each bar's relative volume is split into buys and sells
     with Bulk Volume Classification (Easley, Lopez de Prado & O'Hara,
     2012), giving net order flow x_t.
    -Displacement: flow decays per the paper's recursion (A.2),
     D_t = e^(-rho) * D_(t-1) + kappa * x_t.
    -Calibration: with a random-walk fundamental, the next bar's expected
     return is -(1 - e^(-rho)) * D_t. Regressing next-bar returns on decayed
     flow over a grid of rho values picks the resilience that fits best,
     and the slope gives kappa. Each bar is signalled with a fit that only
     uses earlier bars, and the strategy stays flat unless the reversal is
     statistically significant.
Entries fire when displacement sits at least entry_displacement_sigma daily
standard deviations below steady state. Exits fire when most of that
displacement has decayed, price falls through a volatility stop, or the
trade outlives a few half-lives.
"""

_erf = np.vectorize(math.erf, otypes=[float])

class SupplyDemand(Strategy):
    flow_window = 20
    min_half_life = 0.5
    max_half_life = 20
    half_life_steps = 25
    estimation_window = 250
    min_estimation_bars = 60
    #Stricter than the usual 2 because the best of half_life_steps fits is
    #kept; at 2, pure random walks look "reliable" on ~18% of bars
    min_t_stat = 3.0
    entry_displacement_sigma = 1.0
    exit_displacement_fraction = 0.25
    stop_loss_sigma = 2.0
    max_holding_half_lives = 3

    def generate_signals(self):
        """
        Buys when the fitted order book model puts price well below its
        steady state after a sell shock, then exits once the displacement
        has decayed, at a volatility stop, or after max_holding_half_lives
        half-lives - whichever comes first.

        Also adds the model's per-bar state to the DataFrame: signed_flow,
        half_life (ln 2 / rho, in bars), kappa, reversal_t_stat,
        displacement (log-price distance from steady state) and
        steady_state (the price the model expects to revert to).
        """
        close = self.df["Close"].to_numpy(dtype=float)
        log_close = np.log(close)
        returns = np.diff(log_close, prepend=np.nan)
        #Normalizers only use prior bars so a shock bar can't mute itself
        volatility = pd.Series(returns).rolling(self.flow_window).std().shift(1).to_numpy()
        flow = self._signed_flow(returns, volatility)

        half_lives = np.geomspace(self.min_half_life, self.max_half_life, self.half_life_steps)
        decay = 0.5 ** (1 / half_lives)  #e^(-rho) with rho = ln(2) / half_life
        decayed_flow = self._decayed_flow(flow, decay)
        best, slope, t_stat, estimated = self._fit_resilience(decayed_flow, returns, np.isfinite(flow))

        bars = np.arange(len(close))
        kappa = -slope / (1 - decay[best])
        reliable = estimated & (t_stat <= -self.min_t_stat) & (volatility > 0)
        #Negative displacement means price sits below its steady state
        displacement = np.where(reliable, kappa * decayed_flow[best, bars], np.nan)

        self.df["signed_flow"] = flow
        self.df["half_life"] = np.where(estimated, half_lives[best], np.nan)
        self.df["kappa"] = np.where(estimated, kappa, np.nan)
        self.df["reversal_t_stat"] = np.where(estimated, t_stat, np.nan)
        self.df["displacement"] = displacement
        self.df["steady_state"] = close * np.exp(-displacement)

        signal = np.zeros(len(close), dtype=int)
        in_position = False

        for i in range(len(close)):
            if in_position:
                #Manage the trade with the fit it was entered on, so later
                #refits can't move the exit
                remaining = entry_kappa * decayed_flow[entry_fit, i]
                hit_stop = log_close[i] <= stop_log_price
                recovered = remaining >= -self.exit_displacement_fraction * entry_gap
                timed_out = i - entry_idx >= max_holding_bars
                if hit_stop or recovered or timed_out:
                    signal[i] = -1
                    in_position = False
                continue

            if not reliable[i] or displacement[i] > -self.entry_displacement_sigma * volatility[i]:
                continue

            signal[i] = 1
            in_position = True
            entry_idx = i
            entry_fit = best[i]
            entry_kappa = kappa[i]
            entry_gap = -displacement[i]
            stop_log_price = log_close[i] - self.stop_loss_sigma * volatility[i]
            max_holding_bars = math.ceil(self.max_holding_half_lives * half_lives[entry_fit])

        self.df["signal"] = signal

    def _signed_flow(self, returns, volatility):
        """
        Net order flow per bar in units of recent average volume, using Bulk
        Volume Classification: the buy share of a bar's volume is
        Phi(r / sigma), so buys minus sells is erf(r / (sigma * sqrt(2))).
        NaN until flow_window bars of history exist.

        Parameters:
            returns (ndarray): Log return of each bar.
            volatility (ndarray): Std of log returns over the prior flow_window bars.
        """
        volume = self.df["Volume"].to_numpy(dtype=float)
        avg_volume = pd.Series(volume).rolling(self.flow_window).mean().shift(1).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            flow = volume / avg_volume * _erf(returns / (volatility * math.sqrt(2)))
        flow[~np.isfinite(flow)] = np.nan
        return flow

    @staticmethod
    def _decayed_flow(flow, decay):
        """
        Exponentially decayed sum of flow for every candidate decay rate,
        S_t = e^(-rho) * S_(t-1) + x_t, so displacement is D_t = kappa * S_t.
        Returns an array shaped (len(decay), len(flow)).

        Parameters:
            flow (ndarray): Signed flow per bar; NaN counts as no flow.
            decay (ndarray): Candidate values of e^(-rho).
        """
        flow = np.nan_to_num(flow)
        decayed = np.zeros((len(decay), len(flow)))
        running = np.zeros(len(decay))
        for i, x in enumerate(flow):
            running = decay * running + x
            decayed[:, i] = running
        return decayed

    def _fit_resilience(self, decayed_flow, returns, flow_ready):
        """
        Walk-forward OLS of each bar's next return on decayed flow, for all
        candidate decay rates at once. The fit used at bar t only sees
        (S_i, r_(i+1)) pairs with i < t, over the last estimation_window of
        them, so no bar is signalled with information from its own future.

        Returns, per bar: the index of the best-fitting decay rate (least
        squared error), that fit's slope and t-stat, and whether enough
        pairs existed to fit at all.

        Parameters:
            decayed_flow (ndarray): Output of _decayed_flow.
            returns (ndarray): Log return of each bar.
            flow_ready (ndarray): True where the bar's signed flow is known.
        """
        n_bars = len(returns)
        next_return = np.append(returns[1:], np.nan)
        usable = flow_ready & np.isfinite(next_return)
        z = np.where(usable, decayed_flow, 0.0)
        y = np.where(usable, next_return, 0.0)

        #Windowed sums from cumulative sums: pairs i in [t - window, t - 1]
        end = np.arange(n_bars)
        start = np.maximum(end - self.estimation_window, 0)
        def window_sum(values):
            running = np.cumsum(values, axis=-1)
            running = np.concatenate([np.zeros(running.shape[:-1] + (1,)), running], axis=-1)
            return running[..., end] - running[..., start]

        count = window_sum(usable.astype(float))
        sum_z, sum_y = window_sum(z), window_sum(y)
        sum_zz, sum_zy, sum_yy = window_sum(z * z), window_sum(z * y), window_sum(y * y)

        with np.errstate(divide="ignore", invalid="ignore"):
            sxx = sum_zz - sum_z ** 2 / count
            sxy = sum_zy - sum_z * sum_y / count
            syy = sum_yy - sum_y ** 2 / count
            slope = sxy / sxx
            sse = syy - slope * sxy
            t_stat = slope / np.sqrt(sse / (count - 2) / sxx)

        sse = np.where(np.isfinite(t_stat), sse, np.inf)
        best = np.argmin(sse, axis=0)
        bars = np.arange(n_bars)
        estimated = (count >= self.min_estimation_bars) & np.isfinite(sse[best, bars])
        return best, slope[best, bars], t_stat[best, bars], estimated
