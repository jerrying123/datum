FROM rust:1-bookworm AS generator
WORKDIR /build
COPY rust ./rust
RUN cargo build --release --manifest-path rust/Cargo.toml --bin datum-params

FROM node:22-bookworm-slim
WORKDIR /app
COPY parameter_studio/datum_parameter_studio/package.json parameter_studio/datum_parameter_studio/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=generator /build/rust/target/release/datum-params /usr/local/bin/datum-params
COPY parameter_studio/datum_parameter_studio/server.js ./
COPY parameter_studio/datum_parameter_studio/public ./public
EXPOSE 8080
USER node
CMD ["node", "server.js"]
