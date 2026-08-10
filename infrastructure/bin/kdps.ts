#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { KdpsStack } from "../lib/kdps-stack.js";

const app = new cdk.App();

new KdpsStack(app, "KdpsProduction", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "ap-south-1",
  },
});
