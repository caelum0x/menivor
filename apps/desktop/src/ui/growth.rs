//! Real inputs for the Trends and Signals sections.
//!
//! Trends scores the creator's own output: the daily count of jobs in the
//! library over the last seven days. Signals scores what the creator measured:
//! hook signals and A/B variant results typed in from their platform analytics.
//! Nothing here is sample data - an empty library or empty fields produce an
//! empty state, never a made-up number.

use gpui::{App, AppContext, Context, Entity};

use crate::ui::components::TextField;
use crate::ui::Shell;
use crate::workspace::JobSnapshot;

/// Days in the trend window.
pub(super) const TREND_DAYS: usize = 7;

/// One A/B variant row: completion rate (percent) and average watch seconds.
pub(super) struct VariantFields {
    pub id: &'static str,
    pub completion: Entity<TextField>,
    pub avg_watch: Entity<TextField>,
}

/// The Signals section's inputs.
pub(super) struct SignalFields {
    pub motion: Entity<TextField>,
    pub contrast: Entity<TextField>,
    pub text: Entity<TextField>,
    pub audio_onset: Entity<TextField>,
    pub variants: Vec<VariantFields>,
}

impl SignalFields {
    pub(super) fn new(cx: &mut Context<Shell>) -> Self {
        let signal = |cx: &mut Context<Shell>, label: &str| {
            let placeholder = format!("{label} (0-1)");
            cx.new(|cx| TextField::new(cx, "", placeholder, false))
        };
        let motion = signal(cx, "Motion");
        let contrast = signal(cx, "Contrast");
        let text = signal(cx, "On-screen text");
        let audio_onset = signal(cx, "Audio onset");
        let variants = ["A", "B", "C"]
            .into_iter()
            .map(|id| VariantFields {
                id,
                completion: cx.new(|cx| {
                    TextField::new(cx, "", format!("Variant {id} completion %"), false)
                }),
                avg_watch: cx.new(|cx| {
                    TextField::new(cx, "", format!("Variant {id} avg watch (s)"), false)
                }),
            })
            .collect::<Vec<_>>();
        // Scores update as the creator types: re-render the shell whenever any
        // input changes.
        let inputs = [&motion, &contrast, &text, &audio_onset]
            .into_iter()
            .cloned()
            .chain(
                variants
                    .iter()
                    .flat_map(|row| [row.completion.clone(), row.avg_watch.clone()]),
            )
            .collect::<Vec<_>>();
        for input in &inputs {
            cx.observe(input, |_, _, cx| cx.notify()).detach();
        }
        Self {
            motion,
            contrast,
            text,
            audio_onset,
            variants,
        }
    }

    /// The hook signals entered so far, or `None` when every field is empty.
    pub(super) fn hook_signals(&self, cx: &App) -> Result<Option<rf_growth::HookSignals>, String> {
        let motion = parse_unit(&self.motion.read(cx).text(), "Motion")?;
        let contrast = parse_unit(&self.contrast.read(cx).text(), "Contrast")?;
        let text = parse_unit(&self.text.read(cx).text(), "On-screen text")?;
        let audio_onset = parse_unit(&self.audio_onset.read(cx).text(), "Audio onset")?;
        if [motion, contrast, text, audio_onset].iter().all(Option::is_none) {
            return Ok(None);
        }
        Ok(Some(rf_growth::HookSignals {
            motion,
            contrast,
            text,
            audio_onset,
        }))
    }

    /// The variants with at least one measured value.
    pub(super) fn variants(&self, cx: &App) -> Result<Vec<rf_growth::Variant>, String> {
        let mut variants = Vec::new();
        for row in &self.variants {
            let completion = parse_non_negative(
                &row.completion.read(cx).text(),
                &format!("Variant {} completion", row.id),
            )?
            .map(|percent| (percent / 100.0).clamp(0.0, 1.0));
            let avg_watch = parse_non_negative(
                &row.avg_watch.read(cx).text(),
                &format!("Variant {} avg watch", row.id),
            )?;
            if completion.is_some() || avg_watch.is_some() {
                variants.push(rf_growth::Variant {
                    id: row.id.to_owned(),
                    completion,
                    avg_watch,
                });
            }
        }
        Ok(variants)
    }
}

fn parse_non_negative(input: &str, label: &str) -> Result<Option<f64>, String> {
    let trimmed = input.trim().trim_end_matches('%').trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    match trimmed.parse::<f64>() {
        Ok(value) if value.is_finite() && value >= 0.0 => Ok(Some(value)),
        _ => Err(format!("{label} must be a non-negative number.")),
    }
}

fn parse_unit(input: &str, label: &str) -> Result<Option<f64>, String> {
    match parse_non_negative(input, label)? {
        Some(value) if value > 1.0 => Err(format!("{label} must be between 0 and 1.")),
        other => Ok(other),
    }
}

/// Jobs created per day over the last [`TREND_DAYS`] days, oldest first.
/// `None` when the library has no dated job in the window.
pub(super) fn library_trend_series(jobs: &[JobSnapshot]) -> Option<[f64; TREND_DAYS]> {
    let today = today_days()?;
    series_for(jobs, today)
}

fn series_for(jobs: &[JobSnapshot], today: i64) -> Option<[f64; TREND_DAYS]> {
    let mut series = [0.0; TREND_DAYS];
    let first = today - (TREND_DAYS as i64 - 1);
    for job in jobs {
        let Some(day) = parse_day(&job.created_at) else {
            continue;
        };
        if (first..=today).contains(&day) {
            series[(day - first) as usize] += 1.0;
        }
    }
    series.iter().any(|count| *count > 0.0).then_some(series)
}

fn today_days() -> Option<i64> {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs();
    Some((seconds / 86_400) as i64)
}

/// Days since the Unix epoch for an ISO-8601 timestamp's date part
/// (`YYYY-MM-DD...`). Timestamps are UTC from the API.
fn parse_day(timestamp: &str) -> Option<i64> {
    let date = timestamp.get(..10)?;
    let mut parts = date.split('-');
    let year: i64 = parts.next()?.parse().ok()?;
    let month: i64 = parts.next()?.parse().ok()?;
    let day: i64 = parts.next()?.parse().ok()?;
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    Some(days_from_civil(year, month, day))
}

/// Howard Hinnant's days-from-civil: proleptic Gregorian date to epoch days.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = (if year >= 0 { year } else { year - 399 }) / 400;
    let year_of_era = year - era * 400;
    let month_index = if month > 2 { month - 3 } else { month + 9 };
    let day_of_year = (153 * month_index + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workspace::{JobKind, JobState};

    fn job(created_at: &str) -> JobSnapshot {
        JobSnapshot {
            id: "j".into(),
            kind: JobKind::Reel,
            progress: 100,
            state: JobState::Complete,
            result_url: String::new(),
            result_key: String::new(),
            error: String::new(),
            retry_eligible: false,
            created_at: created_at.into(),
            correlation_id: String::new(),
        }
    }

    #[test]
    fn civil_days_match_the_epoch() {
        assert_eq!(days_from_civil(1970, 1, 1), 0);
        assert_eq!(parse_day("2000-03-01T00:00:00Z"), Some(11_017));
    }

    #[test]
    fn series_counts_jobs_per_day_in_the_window() {
        let today = days_from_civil(2026, 9, 23);
        let jobs = [
            job("2026-09-23T10:00:00Z"),
            job("2026-09-23T11:00:00Z"),
            job("2026-09-17T09:00:00Z"),
            job("2026-09-01T09:00:00Z"),
            job(""),
        ];
        let series = series_for(&jobs, today).unwrap();
        assert_eq!(series, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0]);
    }

    #[test]
    fn empty_window_is_none() {
        assert!(series_for(&[job("2020-01-01")], days_from_civil(2026, 9, 23)).is_none());
    }

    #[test]
    fn unit_inputs_are_validated() {
        assert_eq!(parse_unit("0.5", "x").unwrap(), Some(0.5));
        assert!(parse_unit("1.5", "x").is_err());
        assert_eq!(parse_unit(" ", "x").unwrap(), None);
    }
}
