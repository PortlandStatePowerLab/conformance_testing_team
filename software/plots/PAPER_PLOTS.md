# Paper figures

Run from `conformance_testing_team`:

```powershell
python -m software.plots.paper_run_plot PATH_TO_RUN
python -m software.plots.paper_run_plot_flow PATH_TO_RUN
python -m software.plots.paper_run_plot_water PATH_TO_RUN
python -m software.plots.paper_phase_summary_plot PATH_TO_RUN
python -m software.plots.paper_state_verification_plot PATH_TO_RUN
```

The preferred pair is `paper_run_plot` (EnergyTake + red filled power) and
`paper_run_plot_flow` (EnergyTake + blue filled water flow). These save
`paper_energy_take_power` and `paper_energy_take_flow`, respectively, as PDF
and PNG. Both use green EnergyTake, original command colors, and matching
time limits. They omit "Reported" from the axis label. The older experimental
`paper_run_plot_water` remains available as a stacked-panel alternative.

Each command creates a new `paper_*.pdf` and a 300 dpi `paper_*.png`.
Existing screen plots and CSV files are not written. The PDF page is exactly
3.5 inches wide by default, with 8–10 point text. Set `--width` to the final
printed width in inches from your LaTeX template; `--height` sets the height.
Use `--output-directory` to send both formats elsewhere.

```latex
\includegraphics[width=0.49\textwidth]{Images/paper_energy_take_power_water.pdf}
```

The combined plot uses stacked panels without a legend because each series has
its own labeled axis. Clock labels use 24-hour time and retain the screen plots'
scenario-time alignment, not necessarily the original acquisition clock.
`paper_run_plot_water` accepts `--start HH:MM` to override that alignment.

Caption information to include where relevant:

- EnergyTake is reported via CTA-2045, rather than measured electrical energy.
  The phase chart shows end minus start, using the existing nearest-sample
  calculation. Positive values mean increased reported energy needed.
- The combined plot matches the screen plot's omission of isolated state-5
  reports on stations other than WH-4. Use `--include-isolated-state5` to retain
  them. Its Op State band colors represent verification: green Pass, red Fail,
  yellow command grace, gray no expectation. It is not a numeric state trace.
- The standalone verification plot retains all state reports. Reported numbers
  are CTA state codes; the command row gives expected codes. The verification
  row uses the existing 60-second command grace period. Very short intervals
  may be narrow at print scale; the timeline CSV retains exact poll timestamps.
- Power retains the existing compressor startup-spike suppression; water flow
  retains the existing startup treatment. No source data are changed.

The phase-summary metrics table and event timeline are intentionally excluded
from these figures; typeset selected metrics and milestones in LaTeX tables.
