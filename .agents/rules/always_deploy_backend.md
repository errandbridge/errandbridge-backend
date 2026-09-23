Rule: Always deploy the backend to production whenever you make any changes to the backend codebase.

CRITICAL: Deployments for both frontend and backend are hosted on Vercel and are triggered automatically by pushing commits to the 'main' branch on GitHub (e.g., `git commit` and `git push origin main`). DO NOT use the AWS ECS deployment scripts (`build_push_prod_image.py`, `deploy_prod_image.py`) mentioned in the README.md.
