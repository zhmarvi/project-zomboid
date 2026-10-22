IMAGE ?= project-zomboid:local
.PHONY: build validate security-build
build:
	docker buildx build --platform linux/amd64 --pull --load --tag $(IMAGE) .
security-build:
	docker buildx build --platform linux/amd64 --pull --no-cache --load --tag $(IMAGE) .
validate:
	./scripts/validate.sh
