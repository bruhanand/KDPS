import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as ecsPatterns from "aws-cdk-lib/aws-ecs-patterns";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

const FRONTEND_ORIGINS = "https://kdps-seven.vercel.app";

export class KdpsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      // Test tasks use public subnets with an inbound rule that permits traffic
      // only from the load balancer. This avoids a billable NAT gateway.
      natGateways: 0,
      subnetConfiguration: [
        { name: "public", subnetType: ec2.SubnetType.PUBLIC },
        { name: "database", subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      ],
    });

    const databaseSecret = new rds.DatabaseSecret(this, "DatabaseSecret", {
      username: "kdpsapp",
    });
    const djangoSecret = new secretsmanager.Secret(this, "DjangoSecret", {
      generateSecretString: { generateStringKey: "DJANGO_SECRET_KEY", secretStringTemplate: "{}" },
    });

    const database = new rds.DatabaseInstance(this, "Database", {
      engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.VER_18_3 }),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      credentials: rds.Credentials.fromSecret(databaseSecret),
      databaseName: "kdps",
      // Test profile: the AWS free plan accepts only a micro RDS instance and
      // permits a single Availability Zone. Restore the production settings
      // before the live launch.
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      multiAz: false,
      allocatedStorage: 20,
      maxAllocatedStorage: 100,
      storageType: rds.StorageType.GP3,
      storageEncrypted: true,
      // The test account's current RDS plan permits a maximum one-day retention.
      // Restore the seven-day production baseline before moving live.
      backupRetention: cdk.Duration.days(1),
      deletionProtection: true,
      publiclyAccessible: false,
      cloudwatchLogsExports: ["postgresql"],
      cloudwatchLogsRetention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const cluster = new ecs.Cluster(this, "Cluster", { vpc });
    const service = new ecsPatterns.ApplicationLoadBalancedFargateService(this, "Api", {
      cluster,
      desiredCount: 1,
      publicLoadBalancer: true,
      taskImageOptions: {
        image: ecs.ContainerImage.fromAsset("../app/backend"),
        containerPort: 8000,
        environment: {
          DATABASE_HOST: database.instanceEndpoint.hostname,
          DATABASE_NAME: "kdps",
          DATABASE_PORT: database.instanceEndpoint.port.toString(),
          DJANGO_ALLOWED_HOSTS: "*",
          DJANGO_DEBUG: "0",
          CORS_ALLOWED_ORIGINS: FRONTEND_ORIGINS,
          CSRF_TRUSTED_ORIGINS: FRONTEND_ORIGINS,
          JWT_COOKIE_SECURE: "1",
          JWT_COOKIE_SAMESITE: "None",
        },
        secrets: {
          DATABASE_USER: ecs.Secret.fromSecretsManager(databaseSecret, "username"),
          DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(databaseSecret, "password"),
          DJANGO_SECRET_KEY: ecs.Secret.fromSecretsManager(djangoSecret, "DJANGO_SECRET_KEY"),
        },
        logDriver: ecs.LogDrivers.awsLogs({ streamPrefix: "api" }),
      },
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      assignPublicIp: true,
      taskSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      circuitBreaker: { rollback: true },
      minHealthyPercent: 100,
    });

    database.connections.allowDefaultPortFrom(service.service, "Django API to PostgreSQL");
    service.targetGroup.configureHealthCheck({ path: "/api/health" });

    new cdk.CfnOutput(this, "ApiOrigin", { value: `http://${service.loadBalancer.loadBalancerDnsName}` });
  }
}
