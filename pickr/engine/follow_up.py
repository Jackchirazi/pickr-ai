"""
Pickr AI - Follow-Up Sequencer (DEPRECATED in v2)
Follow-up logic has been absorbed into the main pipeline.
Email sequence timing is managed via email_jobs table with scheduled_at timestamps.
See: pickr/pipeline.py → create_email_sequence()
"""
# Follow-up timing is defined in pickr/config.py → FOLLOWUP_TIMING
# Email jobs are created in pipeline.py with scheduled_at based on timing
# The worker (scheduler.py) processes queued jobs automatically
